# Research Packet

Run date: 2026-09-28

## 1. Why the AOSP system/vendor boundary decides upgrade cost

- Pillar: Architecture deep dives
- Format: deep dive
- Angle: Treat partition boundaries as long-term product architecture, not cleanup work.
- Sources:
  - https://source.android.com/docs/core/architecture
  - https://source.android.com/docs/core/architecture/partitions
  - https://source.android.com/docs/core/architecture/hal

## 2. AIDL HALs as contracts, not plumbing

- Pillar: Architecture deep dives
- Format: myth vs reality
- Angle: Explain why interface stability and VINTF declarations matter for device maintenance.
- Sources:
  - https://source.android.com/docs/core/architecture/aidl/aidl-hals

## 3. Android.bp mistakes that slow down platform teams

- Pillar: Build system
- Format: mistake I made / lesson learned
- Angle: Show how unclear module ownership causes avoidable build churn.
- Sources:
  - https://source.android.com/docs/setup/build

## 4. Lunch targets are product decisions

- Pillar: Build system
- Format: checklist
- Angle: Connect build variants and product configuration to repeatable device delivery.
- Sources:
  - https://source.android.com/docs/setup/build/building

## 5. SELinux policy is where Android customization becomes honest

- Pillar: Security
- Format: short opinion
- Angle: Explain why permissive policy hides architecture problems.
- Sources:
  - https://source.android.com/docs/security/features/selinux

## 6. AVB is not a checkbox for production Android devices

- Pillar: Security
- Format: deep dive
- Angle: Frame verified boot as part of product trust and update safety.
- Sources:
  - https://source.android.com/docs/security/features/verifiedboot

## 7. Custom ROM work becomes expensive when product logic leaks everywhere

- Pillar: Customization
- Format: checklist
- Angle: Describe how to keep product-specific changes maintainable.
- Sources:
  - https://source.android.com/docs/core/architecture/partitions

## 8. BSP bring-up is not finished when the board boots

- Pillar: Customization
- Format: short opinion
- Angle: Explain the gap between booting once and building a maintainable Android product.
- Sources:
  - https://source.android.com/docs/core/architecture
  - https://source.android.com/docs/compatibility
