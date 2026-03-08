# Output Schema — Intelligent Validation Engine
## Smart Resume Audit & Verification System

The engine outputs a single JSON file with **four top-level keys**.

---

## Top-Level Structure

```json
{
  "summary": { ... },
  "validated_sections": { ... },
  "invalid_sections": { ... },
  "grey_area": { ... }
}
```

---

## `summary`

Quick statistics over the entire validation run.

| Field | Type | Description |
|---|---|---|
| `total_checks` | int | Total number of individual field checks performed |
| `validated_count` | int | Number of checks that passed |
| `invalid_count` | int | Number of checks that failed hard rules |
| `grey_area_count` | int | Number of checks that landed in grey area |

---

## `validated_sections`

A flat map of **path → entry** for every check that passed all rules.

```json
"validated_sections": {
  "name": {
    "path": "name",
    "data": "Dhruv Aggarwal",
    "note": ""
  },
  "emails[0]": {
    "path": "emails[0]",
    "data": "aggarwaldhruv419@gmail.com",
    "note": ""
  },
  "urls.linkedin": {
    "path": "urls.linkedin",
    "data": "https://www.linkedin.com/in/...",
    "note": "HTTP 200 — reachable."
  }
}
```

**Entry fields:**
| Field | Description |
|---|---|
| `path` | Dot-notation path to the field in the original JSON |
| `data` | The validated value |
| `note` | Optional informational note (e.g., HTTP status, country-code stripping) |

---

## `invalid_sections`

A flat map of **path → entry** for every check that failed a hard rule.

```json
"invalid_sections": {
  "emails[1]": {
    "path": "emails[1]",
    "data": "bad-email@@broken",
    "error": "Email 'bad-email@@broken' has invalid format."
  },
  "phone_numbers[1]": {
    "path": "phone_numbers[1]",
    "data": "12345",
    "error": "Phone '12345' yields 5 digits after stripping — expected exactly 10."
  },
  "experience[1].duration": {
    "path": "experience[1].duration",
    "data": { "raw": "December 2024 - January 2024", "start": "2024-12-01", "end": "2024-01-01" },
    "error": "Experience[1] (Bad Experience Entry): End date 'January 2024' is before start date 'December 2024' — temporal logic violation."
  }
}
```

**Entry fields:**
| Field | Description |
|---|---|
| `path` | Dot-notation path to the failed field |
| `data` | The raw value that failed |
| `error` | Human-readable error tag explaining the failure |

---

## `grey_area`

A flat map of **path → entry** for ambiguous, incomplete, or suspicious data.

```json
"grey_area": {
  "projects[3].github": {
    "path": "projects[3].github",
    "data": "https://github.com/username/ecommerce-platform",
    "note": "Project[3] (E-commerce Platform) GitHub returned HTTP 404 — dead or broken link."
  },
  "projects[4].description": {
    "path": "projects[4].description",
    "data": { "a": "Some brief description." },
    "note": "Project[4] (Thin Description Project): Thin description (1 bullet); at least 2 bullets recommended."
  }
}
```

**Entry fields:**
| Field | Description |
|---|---|
| `path` | Dot-notation path to the ambiguous field |
| `data` | The raw value |
| `note` | Explanation of why it is grey and what to check manually |

---

## Path Conventions

| Pattern | Example | Meaning |
|---|---|---|
| `fieldname` | `name` | Top-level scalar field |
| `field[N]` | `emails[0]` | Nth item in a list |
| `field.subfield` | `urls.github` | Nested object key |
| `field[N].subfield` | `projects[2].duration` | Sub-field of the Nth list item |

---

## Hard Failure Rules (→ `invalid_sections`)

| Rule | Condition |
|---|---|
| Email format | Does not match `^[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}$` |
| Phone digits | Stripped digit count ≠ 10 (and > 9) or unsupported country code |
| URL reachability | HTTP ≥ 400 or connection error after retries |
| Temporal order | End date < start date for experience or projects |
| Name with digits | Name contains numeric characters |
| Name length | Name exceeds 100 characters |

## Grey-Area Triggers (→ `grey_area`)

| Trigger | Condition |
|---|---|
| Single-word name | Name has only one part |
| Ambiguous phone | 8 or 9 digits after stripping |
| Thin description | Fewer than 2 bullet points |
| Missing duration | No `duration` field provided |
| Future project end | Project end date is in the future (not explicitly "Present") |
| Missing grade | Education entry has no grade |
| Experience overlap | Multiple experience entries conceptually overlap |

## Pass Conditions (→ `validated_sections`)

All other fields that satisfy their respective format, logical, and liveness checks.
