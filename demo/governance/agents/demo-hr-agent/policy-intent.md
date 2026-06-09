# Policy Intent — Meridian Health HR Hiring Agent

## What this agent does
This agent screens job applicants for Meridian Health clinical and
administrative roles. It reads resumes, ranks candidates, and assists
hiring managers with shortlist recommendations. It is classified as a
high-risk AI system under the Colorado AI Act because it substantially
assists in consequential employment decisions.

## What it is allowed to access
- Applicant tracking system API to read resumes and employment history
- OpenAI GPT-4o for resume screening and candidate ranking

## What it must never do
- Access PHI or medical records of applicants
- Make a final hiring decision without human review and user consent logged
- Use protected characteristics (race, gender, age, disability) in scoring
- Transfer applicant PII to any external system not listed above
- Process applications for roles outside approved US regions

## Compliance notes
This agent is subject to the Colorado AI Act (SB 24-205) and EEOC
fair hiring regulations. All screening decisions must be explainable
and must not discriminate based on protected characteristics.
Human review is required before any consequential hiring decision.
