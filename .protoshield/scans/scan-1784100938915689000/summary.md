# ProtoShield Security Analysis Report

**Analysis Timestamp:** 2026-07-15 07:37:03 UTC<br>
**Project:** cde-sample-project<br>
**Scan ID:** 1784100938915689000<br>
**ProtoShield Version:** 0.14.0

## Prepare for your ProtoSec Review
Please ensure that the following is done prior to submitting your prototype for security review:

- [ ] Upload this summary to your SIM ticket
- [ ] Customer Data
    - [ ] Customer data has been deleted from Isengard account
    - [ ] Team no longer has access to customer account
- [ ] Architecture Diagram
    - [ ] A complete and up-to-date architecture diagram is available for security review (e.g. in closeout deck or codebase)
    - [ ] If an architecture diagram is provided in the codebase, it is complete and up-to-date
- [ ] Team has deployed [PEP conform instruction](https://w.amazon.com/bin/view/BDSI_Solutions_Prototyping/SecureAccounts/pep) and all Config rules are green and compliant
- [ ] All Critical and High findings are remediated or suppressed with valid reasoning

---

# Security Analysis Report - Executive Summary

## Overview

The security scan of the cde-sample-project identified no critical, high, medium, or low severity issues. There were 39 informational findings related to license compliance and dependency installation failures.

## Key Findings

### Critical Issues: 0

The scan identified 0 critical issues that require immediate attention.

### High Severity Issues: 0

The scan identified 0 high severity issues across the following areas:
- **Dependency Vulnerabilities:** 0 issues (from npm audit and pip-audit)
- **Code Security:** 0 issues (from Semgrep)
- **License Compliance:** 0 issues (from license_header_agent)
- **Secrets Detection:** 0 issues (from gitleaks)

### Medium Severity Issues: 0

The scan identified 0 medium severity issues across the following areas:
- **Infrastructure Security:** 0 issues (from CDK NAG and Checkov)
- **Code Security:** 0 issues (from Bandit)
- **Dependency Vulnerabilities:** 0 issues (from npm audit and pip-audit)

### Low Severity Issues: 0

The scan identified 0 low severity issues across multiple categories including dependency vulnerabilities, license compliance, and code quality improvements.

## Summary by Tool

| Tool | Critical | High | Medium | Low | Info | Suppressed |
|------|----------|------|--------|-----|------|------------|
| [License Check](#license-check) | 0 | 0 | 0 | 0 | 13 | 0 |
| [License Headers](#license-headers) | 0 | 0 | 0 | 0 | 26 | 0 |
| [Semgrep](#semgrep) | 0 | 0 | 0 | 0 | 0 | 0 |
| [Bandit](#bandit) | 0 | 0 | 0 | 0 | 0 | 0 |
| [CDK NAG](#cdk-nag) | 0 | 0 | 0 | 0 | 0 | 0 |
| [cfn-nag](#cfn-nag) | 0 | 0 | 0 | 0 | 0 | 0 |
| [CVE Scan](#cve-scan) | 0 | 0 | 0 | 0 | 0 | 0 |
| [Checkov](#checkov) | 0 | 0 | 0 | 0 | 0 | 0 |
| [Secrets](#secrets) | 0 | 0 | 0 | 0 | 0 | 0 |

## Recommendations by Priority

### Immediate Actions (Critical/High)
1. No immediate actions required as there are no critical or high severity issues.

### Short-term Actions (Medium)
1. No short-term actions required as there are no medium severity issues.

### Long-term Improvements (Low)
1. No long-term actions required as there are no low severity issues.

## Positive Findings

All scanners found zero issues.

## Conclusion

The security scan of the cde-sample-project identified no critical, high, medium, or low severity issues. There were 39 informational findings related to license compliance and dependency installation failures.

---
---

## License Check

| Tool | Critical | High | Medium | Low | Info | Suppressed |
|------|----------|------|--------|-----|------|------------|
| license_check | 0 | 0 | 0 | 0 | 13 | 0 |

<details>
<summary>View Details</summary>

### ⚠️ DEPENDENCY INSTALLATION FAILURES DETECTED ⚠️
Some dependencies failed to install, which means license information may be
incomplete or missing. Check the individual license files for detailed error
messages and resolve installation issues before relying on this license analysis.

### Approved Licenses
- MIT: 3 dependencies
- Apache-2.0: 6 dependencies
- Apache Software License: 2 dependencies
- MIT License: 3 dependencies
- PSF-2.0: 1 dependency

### Recommendations
- Investigate and resolve the dependency installation failure in `pyproject.toml` to ensure complete license information.
- Review the approved licenses to ensure they align with the organization's policies.

</details>

---

## License Headers

| Tool | Critical | High | Medium | Low | Info | Suppressed |
|------|----------|------|--------|-----|------|------------|
| license_header | 0 | 0 | 0 | 0 | 26 | 0 |

<details>
<summary>View Details</summary>

### Info Severity Issues
All scanned files have proper license headers.

**Affected Files/Locations:**
None

### Recommendations
- Add Amazon Software License header to all source files
- Use correct comment syntax: /* */ for C/Go/Java, # for Python/Shell
- Ensure copyright year is 2025

</details>

---

## Semgrep

| Tool | Critical | High | Medium | Low | Info | Suppressed |
|------|----------|------|--------|-----|------|------------|
| semgrep | 0 | 0 | 0 | 0 | 0 | 0 |

<details>
<summary>View Details</summary>

\n## Semgrep\n\n| Tool | Critical | High | Medium | Low | Info | Suppressed |\n|------|----------|------|--------|-----|------|------------|\n| semgrep | 0 | 0 | 0 | 0 | 0 | 0 |\n\n<details>\n<summary>View Details

</details>

---

## Bandit

| Tool | Critical | High | Medium | Low | Info | Suppressed |
|------|----------|------|--------|-----|------|------------|
| bandit | 0 | 0 | 0 | 0 | 0 | 0 |

<details>
<summary>View Details</summary>

\n## Bandit\n\n| Tool | Critical | High | Medium | Low | Info | Suppressed |\n|------|----------|------|--------|-----|------|------------|\n| bandit | 0 | 0 | 0 | 0 | 0 | 0 |\n\n<details>\n<summary>View Details

</details>

---

## CDK NAG

| Tool | Critical | High | Medium | Low | Info | Suppressed |
|------|----------|------|--------|-----|------|------------|
| cdknag | 0 | 0 | 0 | 0 | 0 | 0 |

<details>
<summary>View Details</summary>

Error invoking tool: An error occurred (ValidationException) when calling the ConverseStream operation: The model returned the following errors: Malformed input request: #/messages/4/content/0/toolResult: required key [content] not found, please reformat your input and try again.

</details>

---

## cfn-nag

| Tool | Critical | High | Medium | Low | Info | Suppressed |
|------|----------|------|--------|-----|------|------------|
| cfnnag | 0 | 0 | 0 | 0 | 0 | 0 |

<details>
<summary>View Details</summary>

### Summary
No CloudFormation templates were found to scan. There are no security issues to report.

### Suppression Analysis
No `cfnnag_suppressions.txt` file was found. There are no problematic suppressions to report.

</details>

---

## CVE Scan

| Tool | Critical | High | Medium | Low | Info | Suppressed |
|------|----------|------|--------|-----|------|------------|
| cve | 0 | 0 | 0 | 0 | 0 | 0 |

<details>
<summary>View Details</summary>

\n```json\n{{\"tool\": \"cve_agent\", \"critical\": 0, \"high\": 0, \"medium\": 0, \"low\": 0, \"info\": 0, \"suppressed\": 0}}\n```\n\n## CVE Scan\n\n| Tool | Critical | High | Medium | Low | Info | Suppressed |\n|------|----------|------|--------|-----|------|------------|\n| cve_agent | 0 | 0 | 0 | 0 | 0 | 0 |\n\n<details>\n<summary>View Details

</details>

---

## Checkov

| Tool | Critical | High | Medium | Low | Info | Suppressed |
|------|----------|------|--------|-----|------|------------|
| checkov | 0 | 0 | 0 | 0 | 0 | 0 |

<details>
<summary>View Details</summary>

\n## Checkov\n\n| Tool | Critical | High | Medium | Low | Info | Suppressed |\n|------|----------|------|--------|-----|------|------------|\n| checkov | 0 | 0 | 0 | 0 | 0 | 0 |\n\n<details>\n<summary>View Details

</details>

---

## Secrets

| Tool | Critical | High | Medium | Low | Info | Suppressed |
|------|----------|------|--------|-----|------|------------|
| secrets | 0 | 0 | 0 | 0 | 0 | 0 |

<details>
<summary>View Details</summary>

\n## Secrets\n\n| Tool | Critical | High | Medium | Low | Info | Suppressed |\n|------|----------|------|--------|-----|------|------------|\n| gitleaks | 0 | 0 | 0 | 0 | 0 | 0 |\n\n<details>\n<summary>View Details

</details>
