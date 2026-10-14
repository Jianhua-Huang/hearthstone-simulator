param(
    [string]$DecompiledDirectory = (Join-Path $PSScriptRoot '..\..\reports\decompiled\entity')
)
$ErrorActionPreference = 'Stop'
$entitySource = Get-Content -LiteralPath (Join-Path $DecompiledDirectory 'Player.cs')
$textSource = Get-Content -LiteralPath (Join-Path $DecompiledDirectory 'TextUtils.cs')
$spellpowerMethod = $entitySource[274..320] -join "`n"
$textMethods = $textSource[287..403] -join "`n"
$parameterClass = $textSource[6..19] -join "`n"
if (-not $spellpowerMethod.StartsWith("`tpublic int TotalSpellpower(")) {
    throw 'Player.cs source layout differs from the inspected build. Reinspect before changing the extraction range.'
}
if (-not $textMethods.StartsWith("`tprivate static string TransformCardTextImpl(")) {
    throw 'TextUtils.cs source layout differs from the inspected build. Reinspect before changing the extraction range.'
}
function Get-FragmentHash([string]$source) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($source)
    return [System.Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($bytes))
}
$sourceMetadata = @(
    [pscustomobject]@{ file = 'Player.cs'; method = 'Player.TotalSpellpower'; lines = '275-321'; sha256Utf8Lf = (Get-FragmentHash $spellpowerMethod) },
    [pscustomobject]@{ file = 'TextUtils.cs'; method = 'TextUtils.TransformCardTextImpl'; lines = '288-391'; sha256Utf8Lf = (Get-FragmentHash ($textSource[287..390] -join "`n")) },
    [pscustomobject]@{ file = 'TextUtils.cs'; method = 'TextUtils.SafeAddInt'; lines = '393-404'; sha256Utf8Lf = (Get-FragmentHash ($textSource[392..403] -join "`n")) }
)
$expectedHashes = @(
    '5758C0AF3BBD2121694DDC873FC77CA5E42F76580DC71051EB194D46F08D4B1C',
    '5D4A3CF1C8C5B871887EB6B5FE3EA653CF98DBE832306C2D7BB8ADD7055CC0C1',
    '3CA6387395FB05933DBAB3BBB7178085C879967DC6295BEF96255C4C91E4908C'
)
for ($i = 0; $i -lt $sourceMetadata.Count; $i++) {
    if ($sourceMetadata[$i].sha256Utf8Lf -ne $expectedHashes[$i]) {
        throw "Source fragment $($sourceMetadata[$i].method) differs from the inspected build. Reinspect its method body before running this probe."
    }
}
$tagNames = [regex]::Matches($spellpowerMethod, 'GAME_TAG\.([A-Z_]+)') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
$schoolNames = [regex]::Matches($spellpowerMethod, 'TAG_SPELL_SCHOOL\.([A-Z_]+)') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
$code = @"
using System;
using System.Text;
using System.Collections.Generic;
public enum GAME_TAG { $($tagNames -join ',') }
public enum TAG_SPELL_SCHOOL { $($schoolNames -join ',') }
public class FragmentEntity {
    private Dictionary<GAME_TAG,int> tags = new Dictionary<GAME_TAG,int>();
    public int GetTag(GAME_TAG t) { return tags.TryGetValue(t, out int v) ? v : 0; }
    public bool HasTag(GAME_TAG t) { return GetTag(t) > 0; }
    public void Set(string t, int v) { tags[(GAME_TAG)Enum.Parse(typeof(GAME_TAG), t)] = v; }
}
public class Entity : FragmentEntity {}
public class FragmentPlayer : FragmentEntity {
$spellpowerMethod
}
public static class FragmentText {
$parameterClass
private static StringBuilder s_textBuffer = new StringBuilder(128);
$textMethods
public static string Run(string text, int bonus, int doubles, int healing, int healingDoubles) {
    return TransformCardTextImpl(text, new TransformCardTextParams {
        DamageBonus = bonus, DamageBonusDouble = doubles,
        HealingBonus = healing, HealingDouble = healingDoubles
    });
}
}
"@
Add-Type -TypeDefinition $code
$results = [System.Collections.Generic.List[object]]::new()
function Check-Value([string]$name, $actual, $expected) {
    if ($actual -ne $expected) { throw "$name expected $expected; got $actual" }
    $results.Add([pscustomobject]@{ case = $name; actual = $actual; expected = $expected; passed = $true })
}
$player = [FragmentPlayer]::new()
$entity = [Entity]::new()
$player.Set('CURRENT_SPELLPOWER_BASE', 2)
$player.Set('CURRENT_NEGATIVE_SPELLPOWER', 1)
$player.Set('CURRENT_SPELLPOWER_FIRE', 3)
$player.Set('CURRENT_TEMP_SPELLPOWER_FIRE', 5)
$player.Set('CURRENT_TEMP_SPELLPOWER_BASE', 4)
$entity.Set('CURRENT_SPELLPOWER_BASE', 6)
Check-Value 'ordinary fire spell includes temporary spellpower' ($player.TotalSpellpower($entity, [TAG_SPELL_SCHOOL]::FIRE)) 19
$entity.Set('SECRET', 1)
Check-Value 'secret excludes temporary base and school spellpower' ($player.TotalSpellpower($entity, [TAG_SPELL_SCHOOL]::FIRE)) 10
$entity.Set('SECRET', 0)
$entity.Set('SIGIL', 1)
Check-Value 'sigil excludes temporary base and school spellpower' ($player.TotalSpellpower($entity, [TAG_SPELL_SCHOOL]::FIRE)) 10
$entity.Set('SIGIL', 0)
Check-Value 'school none omits fire spellpower' ($player.TotalSpellpower($entity, [TAG_SPELL_SCHOOL]::NONE)) 11
Check-Value 'damage bonus applies before two doublings' ([FragmentText]::Run('$6', 2, 2, 0, 0)) '*32*'
Check-Value 'negative damage result clamps to zero' ([FragmentText]::Run('$2', -3, 0, 0, 0)) '*0*'
Check-Value 'damage overflow saturates' ([FragmentText]::Run('$2147483647', 1, 2, 0, 0)) '*2147483647*'
Check-Value 'healing bonus applies before doubling' ([FragmentText]::Run('#4', 0, 0, 2, 1)) '*12*'
Check-Value 'negative healing is not clamped by this formatter' ([FragmentText]::Run('#2', 0, 0, -3, 0)) '*-1*'
[pscustomobject]@{
    scope = 'Extracted decompiled method bodies compiled with minimal stubs; not the complete game DLL or battle engine.'
    originalAssemblySha256 = 'EB88E1C6E6833BDDC3198BADC043959302942D64AA8EC716656AB3A65D8C746B'
    sourceFragments = $sourceMetadata
    testsPassed = $results.Count
    results = $results
} | ConvertTo-Json -Depth 5
