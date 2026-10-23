# SAIV Grading Clarifications

Announcements from the course coordinator (Assoc. Prof. Zhang Tianwei) issued after
the original requirements and codebase. They are recorded here as received. How this
implementation applies them, and every place it differs from the original documents,
is listed separately in [BACKEND-DEVIATIONS.md](BACKEND-DEVIATIONS.md).

---

## Clarifications on the design requirement and codebase

> Dear students,
>
> Below are some clarifications regarding the design requirement and codebase.
>
> 1. The login endpoint must implement the following: after 10 consecutive failed
>    password attempts on the same account, that account must be blocked and further
>    login attempts must return HTTP 429. This is graded.
> 2. If you have implemented per-IP rate limiting as described in the documentation,
>    please increase the limit values to a large number (e.g., 100,000 per hour), so
>    that the test suite will not be blocked. We have hidden tests to check if this
>    feature has been properly implemented.
> 3. Singapore-only check-ins is graded. Check-ins must be rejected (HTTP 403, or
>    created with status "rejected") when the client IP is a public IP outside
>    Singapore, or the GPS coordinates are outside Singapore. Take the client IP from
>    the X-Forwarded-For header when present (first address), falling back to the
>    socket address; private/local addresses (e.g., 192.168.x.x, 10.x.x.x, 127.x.x.x)
>    may be treated as on-campus and allowed.
> 4. The public tests total 92 points right now.
>
> Best regards,
> Tianwei

---

## Update on the Codebase (29/08/2026)

> Dear students,
>
> There are some other minor updates on the codebase, to address some library
> mismatch issues and clear the comments. Please use the latest version on NTULearn.
> Basically,
>
> - Pinned mediapipe==0.10.18 (newer versions removed mp.solutions)
> - regenerated the endpoint comments in module2-backend/app/main.py to match the API spec,
> - removed the non-existent instructor_id/instructor_name fields from the spec
>
> Thanks to the students and TA who point out these issues.
>
> Best regards,
> Tianwei

---

## Update on the Codebase (Module 3 Dockerfile)

> Dear students,
>
> There is an update on the codebase. For module3-face-recognition/Dockerfile,
> Line 10, it should be libgl1 \ instead of libgl1-mesa-glx \
>
> I have uploaded the new version of code on the NTULearn. Please use it for your
> project.
>
> Best regards,
> Tianwei
