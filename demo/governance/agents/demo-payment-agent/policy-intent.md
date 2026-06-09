# Policy Intent — Apex Capital Loan Processing Agent

## What this agent does
This agent processes consumer loan applications for Apex Capital.
It evaluates applicant creditworthiness, checks financial records,
and makes loan approval or denial recommendations. It is classified
as a high-risk AI system under the Colorado AI Act because it
substantially assists in consequential financial decisions.

## What it is allowed to access
- Credit bureau API to check applicant credit scores (read-only)
- OpenAI GPT-4o for loan application analysis
- Internal ledger for recording approved transaction records

## What it must never do
- Access any data outside US regions (us-east-1, us-west-2)
- Transfer applicant PII to any external system not listed above
- Make a final loan decision without user consent logged
- Call any API not explicitly listed in the tool permissions above
- Process applications for customers located outside the United States

## Compliance notes
This agent is subject to the Colorado AI Act (SB 24-205) and
CFPB fair lending regulations. All loan decisions must be explainable
and must not discriminate based on protected characteristics.
User consent must be captured and logged before any consequential
decision is made on behalf of a customer.
