"""Keep ordinary browser fixtures independent of the optional font provider.

The dedicated pending-font regression deliberately bypasses this helper.
"""


def control_optional_fonts(page):
    page.route('https://fonts.googleapis.com/**', lambda route: route.fulfill(
        content_type='text/css', body='/* Synthetic optional font response. */'))
