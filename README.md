# tourtoise backend

## Deployment

CI/CD is configured with GitHub Actions for the `prod` branch. See [docs/ci-cd.md](docs/ci-cd.md) for required GitHub secrets and production server setup.

## Accounts
- User
- User Profile

## Destinations
- Destination
- Attractions
- Cuisines
- Activity

## Trips
-  Trip Plan for Multiple Destination

# Feature: Building a updo-date Knowledge Based Destination Information
- Design a Web Crawler that Fetches Raw Data
- A summarized LLM to summarize and structurized the data into a structures
- Multiple source checking, validates, verify and analyze
- Human in loop acceptance
- For existing Destination: Run with a scheduler to keep upto-date weekly


# Future work scope
- Comment notification to the reciepent
- Manage multiple comments from different user (instead of making a lot of comment notification, how about updating the single notification if the status is unread)
- Implement multiple destination covering during single trip plan

