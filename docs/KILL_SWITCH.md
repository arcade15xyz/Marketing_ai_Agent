# Kill Switch

The publishing kill switch is controlled by:

```text
PUBLISHING_KILL_SWITCH
```

Publishing is blocked by default. Any value except `false`, `0`, `off`, or `no` blocks publishing.

Recommended default:

```text
PUBLISHING_KILL_SWITCH=true
```

To allow publishing for a deliberate run:

```powershell
$env:PUBLISHING_KILL_SWITCH='false'
python -m src.marketing_agents.publisher --date 2026-09-28 --platform linkedin --execute
```

To stop publishing immediately:

```powershell
$env:PUBLISHING_KILL_SWITCH='true'
```

The kill switch is checked before approval, credential, or API publishing logic.

