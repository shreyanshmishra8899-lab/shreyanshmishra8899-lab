import xml.dom.minidom as minidom

import numpy as np
import pytest
from PIL import Image

from make_ascii_svg import AsciiSvgError, image_to_ascii_grid, render_svg as render_ascii_svg
from make_info_card import render_svg as render_info_card_svg
from profile_config import ProfileConfig, TechCategory


def _assert_valid_xml(svg: str) -> minidom.Document:
    doc = minidom.parseString(svg)
    assert doc.documentElement.tagName == "svg"
    return doc


@pytest.fixture
def sample_config() -> ProfileConfig:
    return ProfileConfig(
        github_username="octocat",
        display_name="Octo & <Cat>",  # deliberately includes XML-sensitive chars
        role="Open to work",
        experience='Interned at "Acme" & Co',
        tech_categories=(
            TechCategory("Languages", ("Python", "C++", "SQL")),
            TechCategory("Frameworks", tuple(f"Tool{i}" for i in range(20))),
        ),
        highlights=(),
    )


class TestInfoCardSvg:
    def test_valid_xml_animated(self, sample_config):
        svg = render_info_card_svg(sample_config, static=False)
        _assert_valid_xml(svg)

    def test_valid_xml_static(self, sample_config):
        svg = render_info_card_svg(sample_config, static=True)
        _assert_valid_xml(svg)
        assert "animation:" not in svg.split("<style>")[1].split("</style>")[0].replace(
            "animation: none", ""
        )

    def test_xml_sensitive_characters_escaped(self, sample_config):
        svg = render_info_card_svg(sample_config, static=True)
        assert "Octo &amp; &lt;Cat&gt;" in svg
        assert "&quot;Acme&quot;" in svg or "&amp;quot;" not in svg

    def test_long_tech_list_wraps_without_overflow(self, sample_config):
        svg = render_info_card_svg(sample_config, static=True)
        doc = _assert_valid_xml(svg)
        width = int(doc.documentElement.getAttribute("width"))
        # No single text line's estimated pixel width should exceed the card.
        import re

        for line in re.findall(r'<tspan class="value"[^>]*>([^<]*)</tspan>', svg):
            estimated_px = len(line) * 7.8 + 170  # label column + char width
            assert estimated_px <= width + 40  # small tolerance


class TestAsciiSvg:
    def _solid_image(self, value: int, size=(200, 200)) -> Image.Image:
        arr = np.full((size[1], size[0]), value, dtype=np.uint8)
        return Image.fromarray(arr, mode="L")

    def test_solid_white_image_is_all_blank_chars(self):
        img = self._solid_image(255)
        grid = image_to_ascii_grid(img, columns=20)
        assert all(set(row) == {" "} for row in grid)

    def test_solid_black_image_is_densest_char(self):
        img = self._solid_image(0)
        grid = image_to_ascii_grid(img, columns=20)
        densest = " .`:-=+*cs#%@"[-1]
        assert all(set(row) == {densest} for row in grid)

    def test_too_few_columns_raises(self):
        with pytest.raises(AsciiSvgError):
            image_to_ascii_grid(self._solid_image(128), columns=2)

    def test_render_svg_valid_xml(self):
        img = self._solid_image(128, size=(100, 100))
        grid = image_to_ascii_grid(img, columns=30)
        svg = render_ascii_svg(grid)
        _assert_valid_xml(svg)

    def test_empty_grid_raises(self):
        with pytest.raises(AsciiSvgError):
            render_ascii_svg([])
