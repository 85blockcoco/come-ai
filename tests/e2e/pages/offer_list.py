class OfferListPage:
    def __init__(self, page, base_url):
        self.page = page
        self.base_url = base_url

    def open(self):
        self.page.goto(self.base_url + "/career")
        self.page.wait_for_load_state("networkidle")