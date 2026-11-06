def install_atlas_fixture(page, read_snapshot):
    """Keep one controllable Atlas connection in the browser across updates."""
    page.expose_function('readAtlasFixture', read_snapshot)
    page.add_init_script('''(() => {
      const request = window.fetch;
      const encode = new TextEncoder();
      let stream;
      window.fixtureAtlas = {
        connections: 0,
        async update() {
          const target = stream;
          const snapshot = await window.readAtlasFixture();
          if (stream !== target) return;
          const event = snapshot ? 'atlas-update' : 'atlas-unavailable';
          target.enqueue(encode.encode(`event: ${event}\\ndata: ${JSON.stringify(snapshot || {})}\\n\\n`));
        },
        heartbeat: () => stream.enqueue(encode.encode(': heartbeat\\n\\n')),
      };
      window.fetch = (url, options) => {
        if (!String(url).includes('/story/atlas-events?') || options?.headers?.Accept !== 'text/event-stream') {
          return request(url, options);
        }
        fixtureAtlas.connections++;
        const body = new ReadableStream({start(controller) {
          stream = controller;
          options.signal.addEventListener('abort', () => {
            if (stream === controller) stream = null;
            controller.close();
          }, {once: true});
          void fixtureAtlas.update();
        }});
        return Promise.resolve(new Response(body, {headers: {'Content-Type': 'text/event-stream'}}));
      };
    })();''')
