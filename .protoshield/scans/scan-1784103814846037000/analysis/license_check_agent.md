```json
{
  "tool": "license_check",
  "critical": 0,
  "high": 0,
  "medium": 0,
  "low": 1,
  "info": 13,
  "suppressed": 0
}
```

## License Check

| Tool | Critical | High | Medium | Low | Info | Suppressed |
|------|----------|------|--------|-----|------|------------|
| license_check | 0 | 0 | 0 | 1 | 13 | 0 |

<details>
<summary>View Details</summary>

### Unapproved Licenses
(see https://policy.a2z.com/docs/82475/publication)

**Affected Dependencies:**
- UNKNOWN: cde-review-pipeline (from /output/scans/licenses/pyproject_toml_python_licenses.txt)

### Approved Licenses
- MIT: 3 dependencies
- Apache-2.0: 6 dependencies
- Apache Software License: 2 dependencies
- MIT License: 3 dependencies
- PSF-2.0: 1 dependency

### Recommendations

- Investigate the "UNKNOWN" license for the dependency "cde-review-pipeline" to ensure it complies with the organization's policy.
- Ensure all dependencies are using approved licenses.

</details>