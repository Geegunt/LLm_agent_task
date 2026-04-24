"""Константы для rule-based ранжирования вакансий."""

ROLE_ALIASES = {
    "backend":      ("backend", "back-end", "бэкенд", "бекенд", "серверн"),
    "frontend":     ("frontend", "front-end", "фронтенд", "react", "vue", "angular"),
    "fullstack":    ("fullstack", "full-stack", "full stack", "фулстек"),
    "devops":       ("devops", "sre", "platform", "инфраструктур", "эксплуатац"),
    "data science": ("data scientist", "data science", "machine learning", "ml", "аналитик данных", "дата"),
    "ai safety":    ("ai safety", "безопасност", "risk", "риск"),
    "android":      ("android", "kotlin"),
    "ios":          ("ios", "swift"),
}

INTERNSHIP_MARKERS = ("стаж", "intern", "trainee", "практик")
JUNIOR_MARKERS = ("junior", "младший")
MIDDLE_MARKERS = ("middle", "мидл")
SENIORISH_TITLE_MARKERS = (
    "senior", "lead", "tech lead", "ведущий", "старший",
    "тимлид", "техлид", "технический лид",
)
