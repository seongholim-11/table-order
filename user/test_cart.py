import unittest

from streamlit.testing.v1 import AppTest


class DirectCartTests(unittest.TestCase):
    def setUp(self):
        self.app = AppTest.from_file("app.py").run()
        self.app.button(key="start_btn").click().run()

    def test_direct_add_repeated_add_and_separate_variants(self):
        app = self.app
        app.button(key="cat_chicken").click().run()
        app.button(key="add_c1").click().run()
        self.assertEqual(app.session_state["cart"]["c1|"]["qty"], 1)
        self.assertFalse(app.radio)
        self.assertFalse(app.number_input)
        app.button(key="add_c1").click().run()
        app.button(key="add_c1-half-seasoned").click().run()
        cart = app.session_state["cart"]
        self.assertEqual(cart["c1|"]["qty"], 2)
        self.assertEqual(cart["c1|"]["unit"], 18000)
        self.assertEqual(cart["c1-half-seasoned|"]["unit"], 11000)
        self.assertEqual(len(cart), 2)
        app.button(key="q_inc_c1-half-seasoned|").click().run()
        self.assertEqual(app.session_state["cart"]["c1-half-seasoned|"]["qty"], 2)
        self.assertFalse(app.exception)

    def test_drink_variants_have_independent_prices_and_quantities(self):
        app = self.app
        app.button(key="cat_soju").click().run()
        for item_id in ("j5", "j5-grapefruit", "j5-ginger", "j6", "j6-grape", "j6-peach"):
            app.button(key=f"add_{item_id}").click().run()
        cart = app.session_state["cart"]
        self.assertEqual(len(cart), 6)
        self.assertEqual(sum(line["unit"] * line["qty"] for line in cart.values()), 40000)
        self.assertTrue(all(line["qty"] == 1 and line["opt"] == "" for line in cart.values()))
        self.assertFalse(app.exception)

    def test_soldout_menu_cannot_be_added(self):
        self.app.button(key="cat_anju").click().run()
        self.assertTrue(self.app.button(key="add_a11").disabled)
        self.assertEqual(self.app.session_state["cart"], {})


if __name__ == "__main__":
    unittest.main()


class SpicyBadgeTests(unittest.TestCase):
    def test_spicy_badge_shows_chili_count(self):
        app = AppTest.from_file("app.py").run()
        app.button(key="start_btn").click().run()
        app.button(key="cat_anju").click().run()
        html = " ".join(e.proto.body for e in app.get("html"))
        self.assertIn("🌶🌶🌶 매운맛", html)
        self.assertIn("🌶🌶 매운맛", html)
        self.assertFalse(app.exception)
