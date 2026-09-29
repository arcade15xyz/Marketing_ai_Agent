# Reddit Draft

Status: needs_rules_check

Title: Android.bp mistakes that slow down platform teams

## Notes

- Draft only. Do not auto-post.
- Check subreddit rules immediately before using this draft.
- Value-first and non-salesy by design; company link is intentionally omitted.

## Content

Title: Android.bp mistakes that slow down platform teams

I have been thinking about this AOSP engineering pattern:

Show how unclear module ownership causes avoidable build churn.

For teams building IoT, automotive, or custom Android devices, the risky part is often not the first successful build. It is whether the change remains understandable when the product needs a board revision, an Android upgrade, or production support.

The review questions I would use:

- Which module, partition, or team owns this behavior?
- Is this generic Android platform logic, product configuration, device-specific code, or vendor implementation?
- Does the change affect build dependencies, HAL contracts, compatibility checks, or update behavior?
- Would a new engineer understand why this exists six months later?

I am curious how other teams handle this in real AOSP/BSP work.

Where do you usually draw the line between a practical product patch and something that will become upgrade debt?

Rules check before posting:

- Confirm the target subreddit allows this type of technical discussion.
- Remove or rewrite anything that reads like promotion.
- Prefer discussion over links.
- Do not post the same draft across multiple subreddits.

