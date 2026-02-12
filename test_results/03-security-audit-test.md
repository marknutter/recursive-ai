# Security Audit Test: OWASP Juice Shop

RLM pointed at [OWASP Juice Shop](https://github.com/juice-shop/juice-shop) (~95K lines, 551 files, 7.4MB) with the query "find security vulnerabilities". Juice Shop is a deliberately vulnerable web application with documented vulnerability categories, making it ideal for measuring recall.

## Test Configuration

- **Target:** juice-shop (shallow clone), 95,448 lines across 551 files
- **Focused scan areas:** routes/ (62 files), lib/ (24 files), models/ (22 files), server.ts
- **Strategy:** `files_balanced` for routes and lib (too flat for `files_directory`), targeted scan for server.ts and models
- **Subagents dispatched:** 6 (4 route groups + 1 lib + 1 server + 1 models, run in parallel)
- **Model:** haiku for all subagents
- **Iterations:** 1 (single pass covered the security-critical code)

## Context Window Efficiency

| Metric | Value |
|---|---|
| Total codebase size | ~7.4 MB |
| Content analyzed by subagents | ~315 KB (routes + lib + models + server.ts) |
| Orchestrator context consumed | ~5 KB (scan metadata + chunk manifests + result summaries) |
| **Leverage ratio** | **~63x** (315KB analyzed / 5KB in orchestrator) |

The orchestrator never saw a single line of Juice Shop source code. All 315KB of analyzed content was extracted and read inside haiku subagents.

## Vulnerability Findings: 83 Total

### By Severity

| Severity | Count |
|---|---|
| High / Critical | 40 |
| Medium | 33 |
| Low | 10 |

### By Category (deduplicated across subagents)

| Category | Findings | Known in Juice Shop? |
|---|---|---|
| **SQL Injection** | 2 (login, search -- both string concatenation) | Yes |
| **NoSQL Injection** | 3 (updateProductReviews, trackOrder $where, showProductReviews $where) | Yes |
| **XSS** | 3 (true-client-ip header, trackOrder, reflected in errors) | Yes |
| **Broken Access Control / IDOR** | 8 (dataExport, order, deluxe, wallet, payment, address, basket, authenticated users) | Yes |
| **Path Traversal** | 6 (ZIP extraction, dataErasure, logfileServer, keyServer, FTP directory, null byte bypass) | Yes |
| **SSRF** | 1 (profileImageUrlUpload) | Yes |
| **Insecure Deserialization** | 2 (YAML load in fileUpload, b2bOrder vm.runInContext RCE) | Yes |
| **XXE** | 1 (fileUpload with noent:true) | Yes |
| **Cryptographic Failures** | 8 (MD5 hashing, hardcoded RSA key, hardcoded HMAC secret, hardcoded API keys x2, hardcoded cookie secret, hardcoded mnemonic, weak coupon encoding) | Yes |
| **Broken Authentication** | 4 (password change bypass, weak JWT verification, CAPTCHA logic error, rate limit bypass) | Yes |
| **Open Redirect** | 1 (redirect substring matching bypass) | Yes |
| **SSTI** | 1 (dataErasure res.render with req.body spread) | Yes |
| **Security Misconfiguration** | 7 (permissive CORS, exposed metrics, exposed encryption keys, directory listings, disabled XSS filter, missing security headers, verbose errors) | Yes |
| **Sensitive Data Exposure** | 4 (unencrypted card storage, unencrypted PII, CAPTCHA answer in response, log file disclosure) | Yes |
| **Race Conditions** | 2 (likeProductReviews, basket/order) | Yes |
| **Code Injection** | 2 (chatbot handler dispatch, eval() in captcha) | Yes |
| **Other** | 8 (missing constraints, deprecated methods, ReDoS risk, client-side verification, etc.) | Partial |

### Coverage vs Juice Shop's 16 Known Categories

| Juice Shop Category | Found? | Notes |
|---|---|---|
| Broken Access Control | Yes | 8 IDOR instances + path traversals |
| Broken Anti-Automation | Partial | Found missing rate limiting, but didn't flag CAPTCHA bypass specifically |
| Broken Authentication | Yes | Password change bypass, JWT weaknesses |
| Cross-Site Scripting (XSS) | Yes | Header injection, reflected XSS |
| Cryptographic Issues | Yes | MD5, hardcoded keys, weak encoding |
| Improper Input Validation | Yes | Multiple injection vectors found |
| Injection | Yes | SQL, NoSQL, SSTI, code injection |
| Insecure Deserialization | Yes | YAML and VM sandbox escape |
| Miscellaneous | Partial | Some code quality issues found |
| Security Misconfiguration | Yes | CORS, headers, directory listings |
| Security through Obscurity | No | Not detected (e.g., hidden admin paths) |
| Sensitive Data Exposure | Yes | Card data, PII, log files |
| Unvalidated Redirects | Yes | Open redirect via substring matching |
| Vulnerable Components | No | Didn't analyze package.json/dependencies |
| XML External Entities (XXE) | Yes | Found in fileUpload |
| Observability Failures | No | Not in scope for code-level audit |

**Category recall: 13/16 (81%)**

The 3 missed categories make sense:
- **Security through Obscurity** -- requires behavioral testing, not code reading
- **Vulnerable Components** -- requires dependency scanning (npm audit), not source analysis
- **Observability Failures** -- about missing logging, hard to detect from code alone

## Notable Findings

**Most impressive catches:**
- SQL injection in both `login.ts:34` and `search.ts:23` with exact line numbers and exploit examples
- SSTI in `dataErasure.ts` via `res.render('dataErasureResult', { ...req.body })` -- subtle and dangerous
- RCE via `vm.runInContext` in `b2bOrder.ts` with safeEval bypass potential
- SSRF in `profileImageUrlUpload.ts` with weak allowlist bypass
- Hardcoded RSA private key in `insecurity.ts:23` used for JWT signing

**False positives / noise:**
- Some findings were duplicated across subagents (e.g., MD5 hashing found by both lib and models subagents)
- A few low-severity "code quality" findings (deprecated methods, missing TypeScript types) aren't really vulnerabilities
- Some severity ratings were inconsistent between subagents

## Process Observations

**What worked well:**
- `files_balanced` strategy split 62 route files into 4 manageable chunks (~50KB each)
- Parallel dispatch of 6 subagents completed in ~40 seconds
- Subagents extracted their own content -- zero source code in orchestrator context
- Targeted scanning (routes/lib/models/server.ts) instead of scanning all 551 files avoided wasting time on i18n JSON, codefixes, and static assets

**What could improve:**
- No second iteration to drill into specific findings with finer granularity
- Didn't scan frontend/ for client-side vulnerabilities
- Didn't analyze package.json for vulnerable dependencies
- Some overlap/duplication across subagent findings that could be deduped
- Could benefit from a "grep-first" pass to find obvious patterns (eval, exec, query concatenation) before chunking

## Comparison to Paper Claims

| Metric | Value | Notes |
|---|---|---|
| **Leverage ratio** | 63x | Approaching the paper's 100x claim at 7.4MB total codebase |
| **Content analyzed** | 315KB | Focused on security-critical code, not entire repo |
| **Orchestrator context** | ~5KB | Only metadata and summaries |
| **Recall** | 81% of known categories | Missed categories require different analysis methods |
| **Subagent parallelism** | 6 concurrent | Could scale to more for larger codebases |
| **Total wall time** | ~3 minutes | Including clone, scan, chunk, dispatch, synthesis |
