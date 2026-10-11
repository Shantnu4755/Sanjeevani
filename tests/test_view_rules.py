from flask.views import MethodView

ALLOWED = {"GET", "POST", "HEAD", "OPTIONS"}


def test_views_only_use_get_and_post(app):
    for name, func in app.view_functions.items():
        view_class = getattr(func, "view_class", None)
        if view_class and issubclass(view_class, MethodView):
            assert set(view_class.methods) <= ALLOWED, f"{name} uses {view_class.methods}"
