from html.parser import HTMLParser
from pathlib import Path

class Page(HTMLParser):
    language = None
    def handle_starttag(self, tag, attrs):
        if tag == 'html': self.language = dict(attrs).get('lang')

page = Page()
text = Path('index.html').read_text()
page.feed(text)
assert page.language == 'en', 'The sample page needs lang="en".'
assert 'A small repair example' in text, 'The original page content must remain.'
print('Sample page language and content checks passed.')
