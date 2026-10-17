"""Check real Cesium lifecycle with synthetic app data and optional live tiles."""
import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:3012")
    parser.add_argument("--preview-origin", help="Load the isolated source server at this local browser origin (for restricted map keys)")
    parser.add_argument("--provider", choices=("google", "geoapify"), default="google")
    parser.add_argument("--config-url", "--google-config-url", dest="config_url", help="Optional local agent/config URL with the selected browser map key; otherwise use test imagery")
    parser.add_argument("--with-gallery", action="store_true")
    args = parser.parse_args()
    errors = []
    warnings = []
    provider_errors = []
    provider_requests = []
    map_types = []
    output = Path("output/playwright")
    output.mkdir(parents=True, exist_ok=True)
    journey = {
        "schema_version": 1,
        "status": "active",
        "revision": 1,
        "place": "Kaifeng",
        "hierarchy": ["Earth", "China", "Henan", "Kaifeng"],
        "granularity": "city",
        "life_stage": "childhood",
        "latitude": 34.7971,
        "longitude": 114.3076,
        "duration_ms": 2800,
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
        project = {"id": "provider-map-fixture", "mode": "self", "profile": {}, "workspace_unlocked": False}
        def fixture_api(route):
            path = route.request.url.split("/api/v1/memoir", 1)[-1].split("?", 1)[0]
            data = {}
            if path == "/projects" or path == f"/projects/{project['id']}":
                if route.request.method == "PATCH":
                    project["profile"].update((route.request.post_data_json or {}).get("profile", {}))
                data = project
            elif path.endswith("/journey"):
                data = {"active_session": None}
            elif path.endswith("/conversations"):
                data = {"items": []}
            return route.fulfill(json=data)
        origin = args.preview_origin or args.base_url
        if args.preview_origin:
            # Keep all app traffic on the isolated source server. Only the
            # browser URL uses the origin already allowed by the map key.
            page.route(f"{origin}/**", lambda route: route.fulfill(response=route.fetch(
                url=route.request.url.replace(origin, args.base_url, 1))))
        page.route("**/api/v1/memoir/**", fixture_api)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: warnings.append(message.text) if message.type in {"warning", "error"} else None)
        provider_host = "tile.googleapis.com" if args.provider == "google" else "maps.geoapify.com"
        page.on("response", lambda response: provider_errors.append(response.text()) if response.status >= 400 and provider_host in response.url else None)
        page.on("request", lambda request: provider_requests.append(request.url) if provider_host in request.url else None)
        page.on("request", lambda request: map_types.append(request.post_data_json.get("mapType")) if "createSession" in request.url else None)
        browser_key = None
        key_field = "google_maps_browser_api_key" if args.provider == "google" else "geoapify_browser_api_key"
        if args.config_url:
            config = page.request.get(args.config_url).json()
            assert config.get("geo_provider", "google") == args.provider, "Config provider differs from --provider"
            browser_key = config.get(key_field)
            assert browser_key, "No browser map key returned by the chosen config endpoint"
        page.add_init_script("""(() => {
            let cesium;
            Object.defineProperty(window, 'Cesium', {
                configurable: true,
                get: () => cesium,
                set: value => {
                    cesium = {...value};
                    const Viewer = value.Viewer;
                    cesium.Viewer = new Proxy(Viewer, {
                        construct(target, args) {
                            const viewer = Reflect.construct(target, args);
                            window.__mapViewer = viewer;
                            const flyTo = viewer.camera.flyTo.bind(viewer.camera);
                            viewer.camera.flyTo = options => {
                                window.__globeStart = {
                                    pitch: viewer.camera.pitch,
                                    height: viewer.camera.positionCartographic.height,
                                    fovy: viewer.camera.frustum.fovy,
                                    aspect: viewer.camera.frustum.aspectRatio,
                                    radius: viewer.scene.globe.ellipsoid.maximumRadius,
                                };
                                flyTo(options);
                            };
                            return viewer;
                        }
                    });
                }
            });
        })();""")
        if not browser_key:
            def cesium_script(route):
                response = route.fetch()
                route.fulfill(response=response, body=response.text() + """
                    Cesium.UrlTemplateImageryProvider = function(options) {
                        window.__mapOptions = options;
                        return new Cesium.GridImageryProvider();
                    };
                    Cesium.Google2DImageryProvider.fromUrl = async options => {
                        window.__mapOptions = options;
                        return new Cesium.GridImageryProvider();
                    };
                """)
            page.route("**/Build/Cesium/Cesium.js", cesium_script)

        def config(route):
            route.fulfill(json={"auth_mode": "test", "geo_provider": args.provider,
                                key_field: browser_key or "test-browser-key"})

        page.route("**/api/v1/memoir/agent/config", config)
        page.route("**/api/v1/memoir/story/state", lambda route: route.fulfill(content_type="application/json", body='{"family_features_enabled":false}'))
        pictures = [{"asset_id": f"test-picture-{index}", "title": "Test reference image",
                     "image_url": "/static/copyme2_icon_light.png", "allowed_actions": {"embed": True}}
                    for index in range(4)] if args.with_gallery else []
        page.route("**/place-photos?**", lambda route: route.fulfill(json={"items": pictures}))
        page.route("**/api/v1/memoir/agent/turn", lambda route: route.fulfill(
            content_type="application/json",
            body=json.dumps({
                "reply": "What do you remember about the streets near your childhood home?",
                "profile_updates": {"story_focus": {"life_stage": "childhood"}},
                "place_journey": journey,
                "place_journey_change": {"changed": True, "revision": 1},
            }),
        ))
        page.goto(f"{origin}/memoir", wait_until="networkidle")
        try:
            page.get_by_role("button", name="Begin my story").click(timeout=10000)
        except Exception:
            print(json.dumps({"page": page.locator("body").inner_text()[:1500], "errors": errors, "warnings": warnings}))
            raise
        expect(page.get_by_role("textbox", name="Your message")).to_be_visible(timeout=20000)
        expect(page.locator(".message-streaming")).to_have_count(0, timeout=20000)
        page.get_by_role("textbox", name="Your message").fill("I grew up in Kaifeng and remember the river.")
        page.get_by_role("button", name="Send message").click()
        expect(page.locator(".place-journey-scene.is-cesium-live")).to_be_visible(timeout=30000)
        page.screenshot(path=str(output / "map-arrival.png"), full_page=True)
        try:
            expect(page.locator(".place-journey-scene.is-cesium-map")).to_be_visible(timeout=30000)
        except AssertionError:
            print(re.sub(r"([?&](?:apiKey|key|session)=)[^&\s\"\\]+", r"\1<redacted>", json.dumps({"errors": errors, "warnings": warnings, "provider_errors": provider_errors})))
            raise
        page.wait_for_function("window.__mapViewer.scene.globe.tilesLoaded")
        page.locator(".place-journey-scene").screenshot(path=str(output / "map-final.png"))
        result = page.evaluate("""() => {
            const v = window.__mapViewer;
            const c = v.scene.canvas;
            const point = v.camera.pickEllipsoid(new Cesium.Cartesian2(c.clientWidth / 2, c.clientHeight / 2));
            const center = Cesium.Cartographic.fromCartesian(point);
            const start = window.__globeStart;
            const halfFov = Math.min(start.fovy / 2, Math.atan(Math.tan(start.fovy / 2) * start.aspect));
            return {
                flat: v.scene.mode === Cesium.SceneMode.SCENE2D,
                longitude: Cesium.Math.toDegrees(center.longitude),
                latitude: Cesium.Math.toDegrees(center.latitude),
                globeFits: Math.asin(start.radius / (start.height + start.radius)) < halfFov,
                globePitch: start.pitch,
                canvas: {width: c.clientWidth, height: c.clientHeight},
                mapUrl: window.__mapOptions?.url,
                roadmap: window.__mapOptions?.mapType,
            };
        }""")
        assert result["flat"], result
        assert result["globeFits"], result
        assert abs(result["globePitch"] + 1.5707963267948966) < 0.001, result
        assert abs(result["longitude"] - journey["longitude"]) < 0.001, result
        assert abs(result["latitude"] - journey["latitude"]) < 0.001, result
        if not browser_key:
            if args.provider == "google":
                assert result["roadmap"] == "roadmap", result
                assert not result.get("mapUrl"), result
            else:
                assert result["mapUrl"].startswith("https://maps.geoapify.com/v1/tile/"), result
                assert not result.get("roadmap"), result
            assert not provider_requests, "Synthetic imagery must not contact live tile providers"
        else:
            assert not provider_errors, provider_errors
            assert provider_requests, result
            if args.provider == "google":
                assert map_types == ["roadmap"], map_types
            result["mapRequests"] = len(provider_requests)
        for width, height in [(823, 780), (1440, 900), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_function("""() => {
                const v = window.__mapViewer;
                const rect = document.querySelector('.place-journey-scene').getBoundingClientRect();
                return Math.abs(v.scene.canvas.clientWidth - rect.width) < 1 &&
                    Math.abs(v.scene.canvas.clientHeight - rect.height) < 1 &&
                    Math.abs(v.scene.drawingBufferWidth - rect.width) < 1 &&
                    Math.abs(v.scene.drawingBufferHeight - rect.height) < 1;
            }""")
            if width > 760:
                scene = page.locator(".place-journey-scene").bounding_box()
                workspace = page.locator(".workspace-media-overview").bounding_box()
                assert scene["y"] + scene["height"] <= workspace["y"] + workspace["height"], scene
        page.set_viewport_size({"width": 1440, "height": 960})
        page.wait_for_function("""() => {
            const v = window.__mapViewer;
            const rect = document.querySelector('.place-journey-scene').getBoundingClientRect();
            return Math.abs(v.scene.drawingBufferWidth - rect.width) < 1 &&
                Math.abs(v.scene.drawingBufferHeight - rect.height) < 1;
        }""")
        page.evaluate("""() => new Promise(resolve => {
            window.__previousMapViewer = window.__mapViewer;
            window.__mapViewer.camera.moveRight(1000);
            const remove = window.__mapViewer.scene.postRender.addEventListener(() => {
                remove();
                window.__previousCamera = Cesium.Cartesian3.clone(window.__mapViewer.camera.position);
                resolve();
            });
            window.__mapViewer.scene.requestRender();
        })""")
        page.get_by_role("button", name=re.compile(r'^Childhood:')).click()
        assert page.evaluate("window.__previousMapViewer === window.__mapViewer"), "Rerender recreated the camera"
        assert page.evaluate("Cesium.Cartesian3.equals(window.__previousCamera, window.__mapViewer.camera.position)"), "Rerender moved the camera"
        page.screenshot(path=str(output / "map-workspace-final.png"), full_page=True)
        assert not errors, errors
        print(json.dumps({"passed": result, "provider": args.provider, "live_tiles": bool(browser_key)}))
        browser.close()


if __name__ == "__main__":
    main()
