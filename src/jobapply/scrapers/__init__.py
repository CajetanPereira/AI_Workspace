"""Job-board scrapers."""
from .linkedin import LinkedInScraper
from .naukri import NaukriScraper

SCRAPERS = {
    "linkedin": LinkedInScraper,
    "naukri": NaukriScraper,
}
