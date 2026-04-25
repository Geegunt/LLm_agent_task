"""Словари и сигналы для разбора пользовательского запроса."""

SKILL_ALIASES: dict[str, str] = {
    "питон":              "python",
    "python":             "python",
    "java":               "java",
    "javascript":         "javascript",
    "js":                 "javascript",
    "typescript":         "typescript",
    "ts":                 "typescript",
    "go":                 "go",
    "golang":             "go",
    "rust":               "rust",
    "c++":                "c++",
    "c#":                 "c#",
    "kotlin":             "kotlin",
    "swift":              "swift",
    "react":              "react",
    "vue":                "vue",
    "angular":            "angular",
    "node.js":            "node.js",
    "django":             "django",
    "fastapi":            "fastapi",
    "flask":              "flask",
    "sql":                "sql",
    "postgresql":         "postgresql",
    "postgres":           "postgresql",
    "mysql":              "mysql",
    "mongodb":            "mongodb",
    "redis":              "redis",
    "docker":             "docker",
    "kubernetes":         "kubernetes",
    "k8s":                "kubernetes",
    "машинное обучение":  "machine learning",
    "machine learning":   "machine learning",
    "глубокое обучение":  "deep learning",
    "нейронные сети":     "deep learning",
    "pytorch":            "pytorch",
    "tensorflow":         "tensorflow",
    "llm":                "llm",
    "nlp":                "nlp",
    "data science":       "data science",
    "аналитик данных":    "data science",
    "аналитика данных":   "data science",
    "анализ данных":      "data science",
    "анализа данных":     "data science",
    "ai safety":          "ai safety",
    "backend":            "backend",
    "бэкенд":             "backend",
    "frontend":           "frontend",
    "фронтенд":           "frontend",
    "fullstack":          "fullstack",
    "full stack":         "fullstack",
    "android":            "android",
    "ios":                "ios",
    "flutter":            "flutter",
    "1с":                 "1с",
    "bitrix":             "bitrix",
    "spark":              "spark",
    "kafka":              "kafka",
    "linux":              "linux",
    "devops":             "devops",
    "api":                "api",
    "rest":               "rest",
    "graphql":            "graphql",
}

TYPE_SIGNALS: dict[str, list[str]] = {
    "full-time": [
        "полная занятость", "полный день", "полный рабочий день",
        "full-time", "fulltime", "постоянная",
    ],
    "part-time": [
        "частичная занятость", "частичную занятость", "частичная", "частичную",
        "неполная занятость", "неполную занятость", "неполная", "неполную",
        "неполный день", "подработка", "чатичная",
        "part-time", "parttime",
    ],
}

LOCATION_SIGNALS: dict[str, list[str]] = {
    "москва":          ["москва", "москве", "moscow", "мск"],
    "санкт-петербург": ["санкт-петербург", "санкт-петербурге", "спб", "питер", "питере", "st. petersburg"],
    "remote":          [
        "удалённо", "удаленно", "удалённая", "удаленная",
        "удалёнка", "удаленка", "удалёнке", "удаленке",
        "remote", "дистанционно",
    ],
    "екатеринбург":    ["екатеринбург", "екб"],
    "новосибирск":     ["новосибирск"],
    "казань":          ["казань"],
}

SENIORITY_SIGNALS: dict[str, list[str]] = {
    "internship": [
        "стажер", "стажёр", "стажё", "стажировка", "стажировку", "стажировки",
        "практика", "практику", "intern", "trainee", "студент", "студентка",
        "без опыта", "первая работа",
    ],
    "junior": ["junior", "джуниор", "джун", "младший", "начинающий"],
}

AMBIGUOUS_INTERNSHIP_SIGNALS = {
    "стажировк", "стажер", "стажёр", "практик", "intern", "trainee",
}

AMBIGUOUS_WORK_SIGNALS = {
    "работ", "разработчик", "инженер", "junior", "джун", "full-time", "fulltime",
}
