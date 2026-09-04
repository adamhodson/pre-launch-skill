# Pre-Launch Checklist Skill Overview
- I'd like to build a skill that will perform a deep analysis of a website/application project to ensure that it meets a variety of testing, functionality, security, and compliance requirements.
- I've broken down a number of different tests and concerns that should be included in the skill below.
- I'd like you to review this list and then brainstorm with me to clarify/improve/expand on everything included. I'd also like you to identify any gaps in the items included, especially when it comes to performance, security, and compliance, and expand the tests/checks to be as comprehensive as possible.  

## Testing & Functionality
- Make sure crash reporting is in place
- Make sure ability to restore purchases exists
- Make sure there is a well-defined support flow
- Make sure app monitoring is in place, i.e. Sentry, PostHog, UptimeRobot, etc.
- Ensure sign up has been tested with a fresh account before launch
- Make sure all test keys hve been swapped for production keys in production environment
- Ensure load testing has been performed against key data objects. 
- Ensure live payments have been tested and confirmed to work
- Ensure all JSON is compressed
- Ensure no illogical DB writes, i.e. 1 row at a time, that will slow down processes
- Ensure no single dependency bottlenecks exist. Audit round trip latency.

## Security
- Row Level Security - make sure enabled
- Ensure no secret keys exposed or hardcoded
- Ensure no database credentials are exposed
- If using firebase, make sure "if true" is not being used
- Make sure all sensitive API endpoints are locked down
- Make sure rate limiting in place on all endpoints, pages, inputs, etc.
- Make sure no sensitive files stored in public buckets
- Make sure storage buckets are not set to public
- If an AI chatbot exists in the application, ensure it has in-depth self-harm response 
- Make sure there are no missing server-side auth checks missing
- Ensure users cannot access other users data 
- Make sure database does not have open or overly permissive read/write permissions
- Make sure no admin routes are left unprotected
- Make sure no debug pages or developer tools are exposed in production
- Make sure build logs do not leak secrets
- Make sure verbose error messages do not leak stack traces or internal details
- Make sure no secrets or sensitive data are committed to git repo or git history
- Make sure no secrets included in frontend JS
- Ensure all inputs have appropriate input validation
- Thoroughly test for SQL and NoSQL injections
- Set hard spend caps on every API
- Make sure a database backup and restore flow exists and has been tested
- Ensure a kill switch exists and has been tested
- Over-the-air hot fix path
- Make sure all file uploads have appropriate validation and checks set so malicious files cannot be uploaded (never allow .php files, .jsp files, or files masked as images for example)
- Make sure uploads stored somewhere so if malicious code is somehow uploaded, it can not be run
- Make sure all webhooks have signature checks and validation. Especially important for payment webhooks.
- Make sure XSS protection exists on all forms, inputs, and anywhere else someone could attempt to inject an XSS attack
- Check for any SQL queries built with string concatenation
- Ensure no user content is rendered as raw HTML
- Ensure no CORS rules are set to *
- Ensure nothing saves an entire request body on update
- Check for any bloated API contracts
- Check for any misused dynamic conditions in the app's ORM
- Ensure the backend API will not just fetch any URL it's handed/loose backend URL rules

## Accessibility & User Experience
- Make sure custom 404 page exists
- Make sure all pages have unique, descriptive meta titles and descriptions
- Make sure Favicon is set
- Make sure sitemap.xml exists
- Make sure all images contain alt text
- Make sure all images compressed and loading appropriate file extensions (i.e. jpg, png and webp)
- Make sure canonical tags are set
- Make sure OG tags are set
- Make sure schema/structured data exists and is relevant (including but not limited to local schema, website schema, organization schema, faq schema, review schema, and any other schema relevant to the site) 
- Ensure LLMS.txt and Robots.txt exist
- Ensure Lang attribution is set
- Ensure all CSS & JS are minified and production ready


## Compliance
- Make sure privacy policy and terms of service pages exist and are correct for the app/website. Make sure if Google Analytics, Meta Pixel, or any other third-party pixels are installed or will be installed that sell data, it includes that the site does sell data. 
- Make sure terms and conditions cover user generated content, data ownership, data privacy, limitation of liability, as-is disclaimer of warranties, indemnification clause, termination rights, class action waiver, and arbitration clause. These should fit the actual business/business model, not just generic. 
- Make sure that all data collection practices are well documented in privacy policy including analytics, ad delivery, etc. 
- Make sure all third-parties that app/website sends data to are named in the privacy policy
- Make sure cookie banner exists
- If the app uses AI in any way, make sure the privacy policy mentions this 
- Make sure the EULA (end user license agreement) exists and is linked in the app description
- Make sure a DMCA policy exists if applicable and that the terms of services includes a takedown clause.
- Make sure there is a way for users to delete their accounts and all related data from inside the app
- Make sure that all user uploads are deleted from storage once account is deleted, not just the account itself
- Make sure no fake testimonials are present on website/app. All "dummy" testimonials must be removed before launch
- Make sure the users can easily cancel their accounts/subscriptions. This should not take longer than signing up for the app.
- If the app includes subscriptions, make sure that it complies with all rules surrounding auto-renewals
- Ensure a free trial does not auto-renew without a reminder being sent first
- Declare all SDKs
- If app collects biometric data (i.e. face scans) make sure it is compliant with all laws for storage and how the data is used
- If the application or website sends email, ensure the emails contain a clear unsubscribe link, honest subject lines, and a physical mailing address if one exists. 
  