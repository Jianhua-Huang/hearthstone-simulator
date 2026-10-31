"""Export a small, selected set of local client UI textures, without client writes."""
import hashlib
import json
import warnings
from pathlib import Path

import UnityPy

ROOT = Path(__file__).resolve().parents[1]
CLIENT = Path(r"D:\游戏\Hearthstone")
NAMES = {
    "ICC_GameplayArea", "RAG_GameplayArea", "STR_GameplayArea_D",
    "KER_GameplayArea", "VarianLL_Playspace", "Turalyon_Playspace",
    "ORG_GroundCorners", "Hero_portrait", "Card_Weapon_Icons_D",
    "Card_Inhand_Minion_Mage", "Card_Inhand_Ability_Mage",
    "GenFX_Card_InPlay_AllyFrame", "GenFX_HeroFrame", "GenFX_Gem_Mana_D",
}


def main():
    warnings.simplefilter("ignore")
    UnityPy.config.FALLBACK_UNITY_VERSION = "6000.3.11f1"
    source = CLIENT / "Data" / "Win"
    dest = ROOT / "web_ui" / "static" / "assets"
    index = json.loads((ROOT / "outputs/web-ui-client-art-20261014/texture-index.json").read_text(encoding="utf8"))
    selected = [x for x in index if x["name"] in NAMES]
    receipts = []
    for bundle in sorted({x["bundle"] for x in selected}):
        env = UnityPy.load(str(source / bundle))
        source_hash = hashlib.sha256((source / bundle).read_bytes()).hexdigest()
        for obj in env.objects:
            if obj.type.name != "Texture2D":
                continue
            texture = obj.read()
            if texture.m_Name not in NAMES:
                continue
            image = texture.image
            filename = texture.m_Name + ".webp"
            image.save(dest / filename, "WEBP", quality=94)
            alpha = image.getchannel("A").getextrema() if image.mode == "RGBA" else None
            receipts.append({"file": filename, "bundle": bundle, "texture": texture.m_Name,
                             "size": list(image.size), "alpha_range": alpha,
                             "source_sha256": source_hash,
                             "output_sha256": hashlib.sha256((dest / filename).read_bytes()).hexdigest()})
    report = {"client": str(CLIENT), "read_only": True,
              "purpose": "selected local experimental battle UI texture inspection",
              "notes": "Raw textures may be UV atlases; use only visually verified complete regions.",
              "visual_inspection": {
                  "recommended_playfield": "VarianLL_Playspace.webp",
                  "alternate_playfield": "Turalyon_Playspace.webp",
                  "playfield_limits": "Central gameplay slab only. Full official boards also use 3D meshes and corner props; these textures are not a complete scene render.",
                  "STR_GameplayArea_D": "Not recommended as a whole image: top edge includes a baked hero/UI fragment.",
                  "ORG_GroundCorners": "UV atlas with visible seams and attached UI strips, not a direct full-board background.",
                  "Card_Inhand_Minion_Mage": "Opaque atlas: central card face x176..844, y8..1015; portrait and text need separate DOM layers.",
                  "Card_Inhand_Ability_Mage": "Opaque atlas with disconnected frame/dragon strips; do not display the full texture.",
                  "GenFX_HeroFrame": "Opaque white center/background; requires explicit frame mask or layered clipping.",
                  "GenFX_Card_InPlay_AllyFrame": "Opaque atlas with extra pieces; requires explicit oval mask or layered clipping.",
              },
              "assets": receipts}
    (dest / "board-art-manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
