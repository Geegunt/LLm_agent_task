from dataclasses import dataclass, field


@dataclass
class Job:
    id: str
    title: str
    company: str
    location: str
    type: str           # занятость: "full-time" | "part-time" | "unknown"; в старом кэше может быть "internship"
    tags: list[str]
    description: str
    posted_at: str = ""
    salary_range: str | None = None
    source: str = ""
    url: str = ""
    collected_at: str = ""
    experience_years: int | None = None


@dataclass
class UserQuery:
    raw: str
    keywords: list[str]
    preferred_type: str | None      # желаемая занятость: "full-time" | "part-time" | None
    preferred_location: str | None
    seniority: str | None = None   # уровень кандидата: "internship" | "junior" | None
    source_query: str = ""         # оптимизированный запрос для API вакансий


@dataclass
class RankedJob:
    job: Job
    score: float
    matched_keywords: list[str]
    score_breakdown: dict[str, float] = field(default_factory=dict)
