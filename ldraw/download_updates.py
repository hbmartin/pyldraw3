"""LDraw library update download functionality."""

import html.parser

import requests

from ldraw.errors import CouldNotDetermineLatestVersionError

UPDATES_PAGE_URL = "https://library.ldraw.org/updates"
TARGET_HREF = "https://library.ldraw.org/library/updates/complete.zip"


class AnchorTagParser(html.parser.HTMLParser):
    """A custom HTML parser to find the data-pan attribute of a specific anchor tag."""

    def __init__(self):
        super().__init__()
        self.target_href = TARGET_HREF
        self.data_pan_value = None
        self.found = False

    def handle_starttag(self, tag, attrs):
        """Extract data-pan attribute from target anchor tag."""
        # Stop parsing if the tag has already been found
        if self.found:
            return

        # Check if the tag is an anchor tag 'a'
        if tag == "a":
            # Convert attributes to a dictionary for easy lookup
            attributes = dict(attrs)
            # Check if the 'href' attribute matches the target URL
            if attributes.get("href") == self.target_href:
                # If it matches, get the 'data-pan' attribute
                self.data_pan_value = attributes.get("data-pan")
                self.found = True


def extract_data_pan_from_html(html_content):
    """Parse HTML content to extract the 'data-pan' attribute from the updates page.

    Args:
        html_content (str): The HTML content to parse.
        url (str): The target href URL to search for.

    Returns:
        str or None: The value of the 'data-pan' attribute, or None if not found.

    """
    parser = AnchorTagParser()
    parser.feed(html_content)
    return parser.data_pan_value


def get_latest_release_id() -> str:
    """Get the latest LDraw library release ID from the updates page."""
    response = requests.get(UPDATES_PAGE_URL)  # noqa: S113
    response.raise_for_status()
    pan = extract_data_pan_from_html(response.text)
    if pan is None:
        raise CouldNotDetermineLatestVersionError
    return pan.split("-")[-1]
