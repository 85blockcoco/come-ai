class BasePage:
    def __init__(self, page, base_url):
        self.page = page
        self.base_url = base_url

    def goto(self, path=""):
        self.page.goto(self.base_url + path)
        self.page.wait_for_load_state("networkidle")