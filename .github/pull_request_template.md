# Pull Request

## Description

<!-- Briefly describe what this PR does -->

## Type of Change
<!-- Mark the relevant option with an 'x' -->

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Security fix
- [ ] Performance improvement
- [ ] Refactoring (no functional changes)

## Related Issues
<!-- Link any related issues here -->
Closes #

## Testing

<!-- Describe the tests you ran to verify your changes -->

- [ ] All existing tests pass locally
- [ ] Added new tests for new functionality
- [ ] Tested in Docker container
- [ ] Tested with database (if applicable)

### Test Commands Run

```bash
# Example:
pytest test_server.py -v
python production_preflight.py --strict
```

## Security Checklist
<!-- Ensure security best practices are followed -->

- [ ] No secrets or credentials committed
- [ ] Security scan passed: `python security_scan.py`
- [ ] Production preflight passed: `python production_preflight.py --strict`
- [ ] No SQL injection vulnerabilities (parameterized queries only)
- [ ] Authentication/authorization properly implemented
- [ ] RLS policies updated (if database schema changed)

## Deployment Checklist
<!-- For production-impacting changes -->

- [ ] Database migrations added (if schema changed)
- [ ] Environment variables documented in .env.example
- [ ] OPERATIONS.md updated (if ops procedures changed)
- [ ] RELEASE_NOTES.md updated
- [ ] Breaking changes documented

## Code Quality
<!-- Verify code quality standards -->

- [ ] Code follows existing style conventions
- [ ] Type hints added for new functions
- [ ] Docstrings added for public functions
- [ ] Error handling implemented properly
- [ ] Logging added for important operations
- [ ] No debug print statements left in code

## Documentation
<!-- Check if documentation needs updates -->

- [ ] README.md updated (if public API changed)
- [ ] CLIENT_INTEGRATION_MANUAL.md updated (if client-facing changes)
- [ ] OPERATIONS.md updated (if operational procedures changed)
- [ ] Code comments added for complex logic

## Performance Impact
<!-- Describe any performance implications -->

- [ ] No performance degradation expected
- [ ] Performance improved (describe how)
- [ ] Performance impact acceptable (describe tradeoff)

## Rollback Plan
<!-- How can this change be rolled back if needed? -->

## Additional Notes

<!-- Any other information reviewers should know -->

---

## Reviewer Checklist
<!-- For code reviewers -->

- [ ] Code review completed
- [ ] Tests are adequate
- [ ] Security considerations addressed
- [ ] Documentation is clear
- [ ] No merge conflicts
- [ ] CI/CD pipeline passes
