# Android.bp mistakes that slow down platform teams

Most Android platform work becomes expensive when the ownership model is discovered too late.

For IoT founders, automotive teams, and CTOs, the question is rarely just "can we make this work once?" The better question is whether the change will still be understandable during the next board revision, Android upgrade, or production support cycle.

## The engineering point

Show how unclear module ownership causes avoidable build churn.

In this area, the useful review habit is to identify ownership before implementation. That means keeping Android.bp modules, product configuration, dependencies, and build variants easy to reason about.

When that ownership is unclear, the first build may still pass locally. The cost usually appears later:

- upgrade work becomes harder to estimate;
- product and vendor assumptions spread into places they do not belong;
- debugging requires more context than the team has written down;
- compatibility checks become late surprises instead of early signals.

## A practical review habit

Before accepting the change, ask:

- Which team or module owns this behavior?
- Is this generic platform logic, product configuration, device-specific code, or vendor-specific implementation?
- Does this change affect a public interface, build dependency, partition boundary, or compatibility requirement?
- Can the next engineer understand why this was changed?
- What will happen when the product moves to a newer Android release?

This is the type of review that prevents AOSP customization from becoming a pile of patches with no ownership model.

## Takeaway

Good AOSP engineering is not just making Android run on custom hardware.

It is making sure the product can still be upgraded, debugged, and maintained after the first successful boot.

For Ftechiz Pvt. Ltd., this is where BSP projects and custom Android ROM work should start: with clean ownership, verified assumptions, and a platform boundary that will survive production.


## Sources

- https://source.android.com/docs/setup/build
