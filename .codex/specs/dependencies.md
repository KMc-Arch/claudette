# Spec: Dependencies

Analyze the project's dependency landscape.

## Sections

### Package Manager
Which package manager(s) are in use? Lock files present?

### Direct Dependencies
List primary dependencies with versions where visible. Group by purpose (framework, utility, dev tooling, etc.).

### Dependency Health
Are versions pinned or floating? Any visibly outdated or deprecated packages? Any known-problematic dependencies?

### Dev vs Production
Clear separation between dev and production dependencies? Any dev dependencies that shouldn't be in production, or vice versa?

### Internal Dependencies
Does the project depend on other local projects, workspaces, or monorepo packages?

### Missing or Redundant
Any functionality that appears to be hand-rolled where a standard dependency exists? Any dependencies imported but apparently unused?

### Findings
Key observations, risks, or recommendations. Be specific.
