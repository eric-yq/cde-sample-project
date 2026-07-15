```json
{
  "tool": "license_check",
  "critical": 0,
  "high": 0,
  "medium": 0,
  "low": 0,
  "info": 13,
  "suppressed": 0
}
```

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