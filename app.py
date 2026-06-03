from flask import Flask, render_template


class StaticSiteFlask(Flask):
    jinja_options = Flask.jinja_options.copy()
    jinja_options.update(
        comment_start_string="{##",
        comment_end_string="##}",
    )


application = StaticSiteFlask(__name__, static_folder="static", static_url_path="")


@application.route("/")
@application.route("/index.html")
def index():
    return render_template("index.html")


@application.route("/catalog.html")
def catalog():
    return render_template("catalog.html")


@application.route("/catalog-homme.html")
def catalog_homme():
    return render_template("catalog-homme.html")


@application.route("/product-tonic.html")
def product_tonic():
    return render_template("product-tonic.html")


@application.route("/subscription.html")
def subscription():
    return render_template("subscription.html")


if __name__ == "__main__":
    application.run(debug=True)
