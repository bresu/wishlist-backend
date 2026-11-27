from markdown_it import MarkdownIt

# Escape raw HTML, reject dangerous link protocols and embedded Markdown images.
parser = MarkdownIt("commonmark", {"html": False, "breaks": True}).enable("strikethrough").disable("image")


def render_description(text: str) -> str:
    return parser.render(text) if text else ""
