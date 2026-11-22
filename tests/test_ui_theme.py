"""主题、字体与素材测试。"""

from __future__ import annotations

import unittest

from tests.qt_helpers import ensure_qt_app

APP = ensure_qt_app()

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402

from xiangqi.client.styles import APP_STYLE  # noqa: E402
from xiangqi.client.ui_theme import (  # noqa: E402
    GAME_BACKDROP_SPEC,
    MENU_BACKDROP_SPEC,
    RicePaperCard,
    apply_app_theme,
    assets_root,
    find_font_asset,
    find_ui_asset,
    load_theme_fonts,
    make_piece_font,
    make_seal_pixmap,
    paper_texture_tile,
    render_backdrop,
    render_result_backdrop,
)


class AssetTests(unittest.TestCase):
    """内置素材必须随源码分发。"""

    def test_ui_assets_exist(self) -> None:
        for name in (
            "menu_landscape.jpg",
            "game_scroll.jpg",
            "result_landscape.jpg",
            "online_landscape.jpg",
            "plum.jpg",
            "bamboo.jpg",
        ):
            with self.subTest(name=name):
                self.assertIsNotNone(find_ui_asset(name))

    def test_fonts_and_licenses_exist(self) -> None:
        for name in (
            "MaShanZheng-Regular.ttf",
            "ZCOOLXiaoWei-Regular.ttf",
            "OFL-MaShanZheng.txt",
            "OFL-ZCOOLXiaoWei.txt",
        ):
            with self.subTest(name=name):
                self.assertIsNotNone(find_font_asset(name))

    def test_audio_assets_exist(self) -> None:
        audio = assets_root() / "audio"
        for name in ("bgm.mp3", "move.mp3", "button.mp3"):
            with self.subTest(name=name):
                self.assertTrue((audio / name).is_file())

    def test_assets_root_points_to_package(self) -> None:
        root = assets_root()
        self.assertTrue(root.is_dir())
        self.assertEqual(root.name, "assets")


class ThemeTests(unittest.TestCase):
    """QSS、字体与位图渲染。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.families = apply_app_theme(APP)

    def test_theme_fonts_registered(self) -> None:
        families = load_theme_fonts()
        joined = " ".join(families)
        self.assertIn("Ma Shan Zheng", joined)
        self.assertIn("ZCOOL", joined)

    def test_style_contains_palette_and_new_selectors(self) -> None:
        self.assertIn("#F5EFE3", APP_STYLE)
        self.assertIn("#9E3B2E", APP_STYLE)
        self.assertIn("turnPill[check=\"true\"]", APP_STYLE)
        self.assertIn("kingBadgeRed", APP_STYLE)
        self.assertIn("kingBadgeBlack", APP_STYLE)

    def test_piece_font(self) -> None:
        font = make_piece_font(24)
        self.assertIsInstance(font, QFont)
        self.assertEqual(font.pixelSize(), 24)
        self.assertIn("KaiTi", font.families())
        self.assertEqual(font.weight(), QFont.Weight.DemiBold)

    def test_paper_texture_renders(self) -> None:
        for dpr in (1.0, 2.0):
            with self.subTest(dpr=dpr):
                pixmap = paper_texture_tile(dpr)
                self.assertFalse(pixmap.isNull())
                self.assertGreater(pixmap.width(), 0)

    def test_seal_and_backdrops_render(self) -> None:
        self.assertFalse(make_seal_pixmap("棋", 32, dpr=1.0).isNull())
        menu = render_backdrop(QSize(400, 600), 1.0, MENU_BACKDROP_SPEC)
        game = render_backdrop(QSize(400, 600), 1.0, GAME_BACKDROP_SPEC)
        result = render_result_backdrop(QSize(480, 400), 1.0, "win")
        for pixmap in (menu, game, result):
            self.assertFalse(pixmap.isNull())

    def test_rice_paper_card_renders(self) -> None:
        card = RicePaperCard(seal_text="棋")
        card.resize(300, 200)
        pixmap = card.grab()
        self.assertFalse(pixmap.isNull())
        card.deleteLater()


if __name__ == "__main__":
    unittest.main()
