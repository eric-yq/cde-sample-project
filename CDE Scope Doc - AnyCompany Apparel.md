CDE ENGAGEMENT SCOPE DOCUMENT

Customer:           AnyCompany Apparel
Contact:            Priya Mehta, Director of Global Digital Experience
Engagement Shape:   Net-New (Greenfield)
Candidate:          [Quan Yuan / ericyq]
Date:               [Jul 13rd, 2026]


CUSTOMER PROBLEM STATEMENT

AnyCompany Apparel operates direct-to-consumer e-commerce across 14 markets
with EU headquarters. Non-English shoppers see product review content that is
either untranslated (English-only) or poorly machine-translated by their
existing reviews vendor. This results in measurably lower conversion rates in
non-English markets — a metric Priya's team has been held to for two years.

The customer wants a pipeline that ingests reviews from their vendor feed,
translates them, generates a concise one- to two-sentence summary in the
shopper's language, and surfaces that summary at the top of the product detail
page (PDP). Volume: ~12,000 new reviews per week across 6 source languages.


EXISTING TECH STACK

- Reviews feed:     Vendor-provided JSON payload (reviewer name, email, text,
                    rating, product ID, language)
- Hosting:          AWS account (non-production sandbox available)
- Languages:        6 source languages (French, German, Spanish + 3 others)
- PDP rendering:    Customer's frontend team owns the page component


WHAT I WILL BUILD

A multi-language review translation and summarization pipeline prototype that:

- Accepts review text as input (from a simulated vendor feed)
- Translates the source review into a target shopper language using Amazon
  Translate
- Summarizes the translated review into a 1–2 sentence overview using Amazon
  Bedrock (LLM-based summarization with quality scoring)
- Includes a quality-gate step that filters out low-confidence translations
  and summaries before surfacing
- Demonstrates end-to-end on 100 synthetic sample reviews in French and German
  (two languages prove the pattern generalizes)

Single pipeline, two language pairs, synthetic data only. No PII processing.


LANDING SURFACE

Customer's sandbox AWS account (non-production, no real customer data).
Deliverable is an IaC stack + pipeline source in customer's repository:

- IaC stack: Lambda functions, S3 buckets (input/output), Step Functions
  workflow, IAM roles
- Pipeline code: translation module, summarization module, quality-gate logic
- Test harness: 100 synthetic reviews + expected outputs for evaluation
- README: deployment steps, architecture diagram, configuration guide,
  instructions for extending to additional languages


TIMELINE

3 weeks.
- Week 1: Pipeline scaffolding, Amazon Translate integration, ingestion of
  synthetic reviews, initial translation quality evaluation
- Week 2: Bedrock summarization integration, quality-gate logic, end-to-end
  pipeline wiring and testing on French + German
- Week 3: Quality tuning, documentation, handoff walkthrough with Priya's team


BOUNDARIES (OUT OF SCOPE)

- Real customer data / PII — synthetic reviews only; real data with reviewer
  name and email is a separate compliance workstream (customer's legal team)
- Production deployment — customer's platform team handles scaling to 12K
  reviews/week, monitoring, and go-live
- PDP redesign — frontend/UX work owned by a different team or partner
- Additional languages beyond French and German — pattern is proven and
  extensible; customer fans out post-handoff


SUCCESS CRITERIA

1. Translation accuracy above a defined quality threshold on 100 synthetic
   reviews (measured via automated evaluation + human spot-check)
2. Summaries are 1–2 sentences, fluent in target language, and factually
   consistent with source review content
3. End-to-end processing latency under 10 seconds per review
4. Quality gate correctly filters low-confidence outputs (demonstrated on
   intentionally noisy test inputs)
5. Customer team can deploy and extend the pipeline independently using the
   README and IaC provided
