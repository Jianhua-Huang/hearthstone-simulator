"""P05 armor, original Dodo residence, exact Doomsayer and native Elementals."""
from dataclasses import asdict, replace
import json
from random import Random
import re
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_native_p05_cards import (
    GAUNTLET, DINOSITTER, DODO, HARBINGER, PAGETURNER, DOOMSAYER,
    ROOTS, load_batch, register_simple_native_p05_cards,
)
from hs_sim.engine import (
    Attack, CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice,
    TargetSpec, TriggerSpec, Zone,
)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (
    AddToHand, ChangeControl, ChoiceOption, Damage, Destroy, GainArmor, Heal,
    InvokeBehavior, LoseArmor, RequestChoice, ReturnToHand, Silence, Transform,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind, TribeChangeSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TEST = 'p05.test.'
YETI = 'CORE_CS2_182'
LOCATION = 'CORE_REV_990'
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())


def registry():
    r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS)
    if any(present) and not all(present):raise AssertionError('Partial P05 registration')
    if not all(present):register_simple_native_p05_cards(r)

    def summon(c, cid):
        return SummonByCard(c.player_id, (SummonEntryMaterial(cid),), SummonCause.capture(c))

    def stored_change(c, cid, tribe):
        e = next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == cid)
        return (ChangeMinionTribes(CardReference.capture(e), TribeChangeSpec('set', (tribe,)), c.source_id),)

    def reenter(c):
        e = c.state.entities[c.target_id]
        return (SummonStoredCard(CardReference.capture(e), c.player_id, cause=SummonCause.capture(c)),)

    def wait(c, extra=()):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', ()),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(TEST+'fail', c.source_id, c.player_id),)), *extra,
        ), source_id=c.source_id),)

    def dodo_wait(c):
        target = c.state.entities.get(c.event.target_id)
        if target is None or target.card_id != DODO or c.event.source_id != target.id:return ()
        return wait(c, (
            ChoiceOption('bounce', 'Return and reenter same physical Dodo', (ReturnToHand(target.id),
                InvokeBehavior(TEST+'reenter', c.source_id, c.player_id, target.id))),
            ChoiceOption('heal', 'Heal owner hero after acceptance', (Heal(c.state.players[1].hero_id, 30, c.source_id),)),
            ChoiceOption('silence', 'Silence source before current copy', (Silence(target.id),)),
            ChoiceOption('control', 'Give source to opponent', (ChangeControl(target.id, 2),)),
        ))

    def early_remove(c):
        if c.event.player_id != c.player_id or c.state.entities[c.event.target_id].card_id != TEST+'elemental':return ()
        source = next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == PAGETURNER), None)
        return () if source is None else (Destroy(source, c.source_id),)

    def damage_wait(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id != PAGETURNER:return ()
        return wait(c)

    scripts = {
        'gain': lambda c: (GainArmor(c.player_id, 4),),
        'lose': lambda c: (LoseArmor(c.player_id, 2, c.source_id),),
        'damage_hero': lambda c: (Damage(c.state.players[c.player_id].hero_id, 2, c.source_id),),
        'wound10': lambda c: (Damage(c.state.players[c.player_id].hero_id, 20, c.source_id),),
        'wound11': lambda c: (Damage(c.state.players[c.player_id].hero_id, 19, c.source_id),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'control': lambda c: (ChangeControl(c.target_id, 2),),
        'transform': lambda c: (Transform(c.target_id, TEST+'elemental'),),
        'elementalize': lambda c: stored_change(c, TEST+'plain', 'elemental'),
        'unelemental': lambda c: stored_change(c, TEST+'elemental', 'dragon'),
        'summon_dodo': lambda c: (summon(c, DODO),),
        'double': lambda c: (summon(c, TEST+'elemental'), summon(c, TEST+'elemental')),
    }
    for name, body in scripts.items():
        key = TEST+name;r.register_behavior(key, body)
        r.register_card(CardDefinition(key, name, CardType.SPELL, on_play=key, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if name in ('kill','silence','control','transform') else None))
    r.register_behavior(TEST+'reenter', reenter)
    r.register_behavior(TEST+'fail', lambda c: (AddToHand(c.player_id, 'p05.missing'),))
    for name, tribes, health in (('elemental', ('elemental',), 4), ('all', ('all',), 4), ('plain', (), 4), ('frail', (), 2)):
        r.register_card(CardDefinition(TEST+name, name, CardType.MINION, attack=1, health=health,
                                       metadata=replace(META, tribes=tribes)))
    r.register_card(CardDefinition(TEST+'unknown', 'Unknown summon tribes', CardType.MINION, health=4))
    r.register_card(CardDefinition(TEST+'dormant', 'Dormant Elemental', CardType.MINION, health=4, dormant_turns=3,
                                   metadata=replace(META, tribes=('elemental',))))
    r.register_card(CardDefinition(TEST+'bonus', 'Spell damage', CardType.MINION, health=8, spell_damage=6, metadata=META))
    for name, event, body in (('dodo_wait', 'stats_changed', dodo_wait), ('early_remove', 'minion_summoned', early_remove),
                              ('damage_wait', 'damage_dealt', damage_wait)):
        key=TEST+name;r.register_behavior(key, body)
        r.register_card(CardDefinition(key, name, CardType.MINION, health=10, metadata=META,
                                       triggers=(TriggerSpec(event, key),)))
    r.validate();return r


class SimpleNativeP05CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()

    def game(self, hand=(), board=(), enemy=(), *, enemy_hand=(), armor=0, active=1, seed=505):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(YETI,)*10, mana=40, max_mana=40, mana_cap=40,
                        armor=armor, hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,)*10,
                        mana=40, max_mana=40, mana_cap=40, hero_power_card_id='HERO_08bp'),
        ), active_player=active, seed=seed), self.r)

    def entities(self,g,cid,p=1,zone='board'):
        return [g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def play(self,g,cid,target=None):
        p=g.state.active_player;source=self.first(g,cid,p,'hand').id
        g.apply(PlayCard(p,source,target,len(g.state.players[p].board)if self.r.card(cid).kind==CardType.MINION else None));return source
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def low(self,hand=(),board=(),enemy=()):
        g=self.game((TEST+'wound10',*hand),board,enemy);self.play(g,TEST+'wound10');return g
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for hidden in('rng_state','resolution_frame','CardReference','MinionReference','BoardPresenceReference','SuccessfulSummonRecord','behavior_id'):
                self.assertNotIn(hidden,public)
        return other

    def test_complete_raw_pins_official_faces_core_identity_and_exact_existing_doomsayer(self):
        d=load_batch();self.assertEqual(tuple(x['record']['id']for x in d['cards']),ROOTS)
        self.assertFalse(d['dependencies']);self.assertEqual(len(d['official_observations']['observations']),12)
        self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        def normalize(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for group in('cards','existing_dependencies','evidence_only','skipped'):
            for row in d[group]:
                raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
                for o in(o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                    face=o['face'];en=o['locale']=='en-us'
                    self.assertEqual(face['name'],raw['name_en'if en else'name'])
                    self.assertEqual(normalize(face['text']),normalize(raw['text_en'if en else'text']))
                    for key,value in(('id',raw['dbf_id']),('manaCost',raw['cost']),('cardSetId',raw['card_set_id']),
                                     ('classId',raw['tags']['CLASS']),('cardTypeId',raw['tags']['CARDTYPE'])):self.assertEqual(face[key],value)
        for row in d['cards']:
            raw=row['record'];card=self.r.card(raw['id']);identity='LOOT_044'if card.id==GAUNTLET else card.id
            self.assertEqual(card.metadata,replace(metadata_from_record(raw),deck_identity=identity))
            self.assertEqual((card.cost,card.attack),(raw['cost'],raw['attack']or 0))
            self.assertEqual(card.durability if card.kind==CardType.WEAPON else card.health,raw['health'])
        existing,=d['existing_dependencies'];self.assertEqual(canonical_digest(asdict(self.r.card(DOOMSAYER))),existing['definition_sha256'])
        self.assertEqual((self.r.card(DOOMSAYER).attack,self.r.card(DOOMSAYER).health),(0,7))
        self.assertEqual(self.r.card(GAUNTLET).metadata.deck_identity,'LOOT_044')
        self.assertEqual(self.r.card(DODO).metadata.tribes,('beast',))
        self.assertEqual(self.r.card(PAGETURNER).metadata.tribes,('elemental',))

    def test_dinositter_current_hand_tribe_gap_remains_explicit_without_partial_adapter(self):
        row,=load_batch()['skipped'];self.assertEqual(row['record']['id'],DINOSITTER)
        self.assertNotIn(DINOSITTER,ROOTS);self.assertIn('printed metadata',row['reason'])

    def test_gauntlet_zero_and_positive_armor_are_native_derived_attack(self):
        for armor in(0,7):
            g=self.game((GAUNTLET,),armor=armor);self.play(g,GAUNTLET)
            weapon=g.state.entities[g.state.players[1].weapon_id]
            self.assertEqual((weapon.base_attack,weapon.attack,weapon.durability),(0,armor,2))
            self.assertEqual(self.hero(g).attack,armor)
            self.assertEqual(g.state.players[1].mana,38)

    def test_gauntlet_gain_loss_and_armor_damage_do_not_accumulate_permanent_attack(self):
        g=self.game((GAUNTLET,TEST+'gain',TEST+'lose',TEST+'damage_hero'),armor=3)
        self.play(g,GAUNTLET)
        for cid,value in((TEST+'gain',7),(TEST+'lose',5),(TEST+'damage_hero',3)):
            self.play(g,cid);weapon=g.state.entities[g.state.players[1].weapon_id]
            self.assertEqual((weapon.attack,self.hero(g).attack,self.hero(g).armor),(value,value,value))
            self.assertEqual(weapon.base_attack,0)
        self.portable(g)

    def test_gauntlet_cannot_attack_heroes_but_normal_minion_combat_wears_durability(self):
        g=self.game((GAUNTLET,),enemy=(YETI,),armor=6);weapon=self.play(g,GAUNTLET)
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
        self.assertEqual(g.snapshot(),saved)
        target=self.first(g,YETI,2).id;g.apply(Attack(1,self.hero(g).id,target))
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual((self.hero(g).armor,g.state.entities[weapon].attack,g.state.entities[weapon].durability),(2,2,1))

    def test_dodo_health_eleven_or_only_armor_does_not_meet_health_condition(self):
        g=self.game((TEST+'wound11',DODO));self.play(g,TEST+'wound11');self.play(g,DODO)
        self.assertEqual([(e.attack,e.health)for e in self.entities(g,DODO)],[(5,5)])
        h=self.game((DODO,),armor=10);self.play(h,DODO)
        self.assertEqual(len(self.entities(h,DODO)),1)

    def test_dodo_health_ten_gains_five_five_and_summons_current_copy_without_extra_battlecry(self):
        g=self.low((DODO,));self.play(g,DODO)
        self.assertEqual([(e.attack,e.health)for e in self.entities(g,DODO)],[(10,10),(10,10)])
        self.assertTrue(all(Keyword.TAUNT in e.keywords for e in self.entities(g,DODO)))
        self.assertEqual(len(g.state.battlecry_history),1);self.assertEqual(g.state.players[1].mana,35)

    def test_dodo_effect_summon_does_not_run_battlecry(self):
        g=self.low((TEST+'summon_dodo',));self.play(g,TEST+'summon_dodo')
        self.assertEqual([(e.attack,e.health)for e in self.entities(g,DODO)],[(5,5)])
        self.assertFalse(g.state.battlecry_history)

    def test_dodo_full_board_keeps_self_buff_without_delivering_copy(self):
        g=self.low((DODO,),board=(YETI,)*6);self.play(g,DODO)
        self.assertEqual(len(self.entities(g,DODO)),1);self.assertEqual(self.first(g,DODO).attack,10)
        self.assertEqual(len(g.state.players[1].board),7)

    def test_dodo_buff_wait_restores_and_same_id_reentry_does_not_receive_old_copy_plan(self):
        g=self.low((DODO,),board=(TEST+'dodo_wait',));source=self.play(g,DODO)
        presence=g.state.entities[source].board_presence_id;other=self.portable(g)
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g,'bounce');self.choose(other,'bounce');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(self.entities(g,DODO)),1)
        self.assertEqual(self.first(g,DODO).id,source)
        self.assertNotEqual(g.state.entities[source].board_presence_id,presence)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(5,5))
        self.portable(g)

    def test_dodo_later_hero_heal_does_not_recompute_accepted_condition(self):
        g=self.low((DODO,),board=(TEST+'dodo_wait',));self.play(g,DODO);self.choose(g,'heal')
        self.assertEqual(self.hero(g).health,30)
        self.assertEqual([(e.attack,e.health)for e in self.entities(g,DODO)],[(10,10),(10,10)])

    def test_dodo_current_copy_reads_silenced_material_after_buff_reactions(self):
        g=self.low((DODO,),board=(TEST+'dodo_wait',));self.play(g,DODO);self.choose(g,'silence')
        self.assertEqual([(e.attack,e.health)for e in self.entities(g,DODO)],[(5,5),(5,5)])
        self.assertTrue(all(Keyword.TAUNT not in e.keywords for e in self.entities(g,DODO)))

    def test_dodo_control_change_keeps_original_residence_and_original_summon_player(self):
        g=self.low((DODO,),board=(TEST+'dodo_wait',));source=self.play(g,DODO);self.choose(g,'control')
        self.assertEqual(g.state.entities[source].controller,2)
        self.assertEqual((len(self.entities(g,DODO)),len(self.entities(g,DODO,2))),(1,1))
        self.assertEqual(self.first(g,DODO).attack,10)

    def test_harbinger_real_death_summons_exact_existing_doomsayer(self):
        g=self.game((TEST+'kill',),board=(HARBINGER,));source=self.first(g,HARBINGER).id
        self.play(g,TEST+'kill',source)
        doom=self.first(g,DOOMSAYER)
        self.assertEqual((doom.attack,doom.health,doom.controller),(0,7,1))
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.card_summon_history[-1].request.materials[0].card_id,DOOMSAYER)

    def test_harbinger_doomsayer_only_owner_start_destroys_active_minions_not_dormancy_or_locations(self):
        g=self.game((TEST+'kill',),board=(HARBINGER,YETI),enemy=(YETI,TEST+'dormant',LOCATION))
        self.play(g,TEST+'kill',self.first(g,HARBINGER).id)
        g.apply(EndTurn(1));self.assertTrue(self.entities(g,DOOMSAYER));self.assertTrue(self.entities(g,YETI,2))
        g.apply(EndTurn(2));self.assertFalse(self.entities(g,DOOMSAYER));self.assertFalse(self.entities(g,YETI));self.assertFalse(self.entities(g,YETI,2))
        self.assertTrue(self.entities(g,TEST+'dormant',2));self.assertTrue(self.entities(g,LOCATION,2));self.portable(g)

    def test_harbinger_silence_and_current_death_controller_use_shared_lifecycle(self):
        g=self.game((TEST+'silence',TEST+'kill'),board=(HARBINGER,));source=self.first(g,HARBINGER).id
        self.play(g,TEST+'silence',source);self.play(g,TEST+'kill',source);self.assertFalse(self.entities(g,DOOMSAYER))
        h=self.game((TEST+'control',TEST+'kill'),board=(HARBINGER,));source=self.first(h,HARBINGER).id
        self.play(h,TEST+'control',source);self.play(h,TEST+'kill',source)
        self.assertEqual((len(self.entities(h,DOOMSAYER)),len(self.entities(h,DOOMSAYER,2))),(0,1))

    def test_pageturner_own_actual_entry_is_elemental_and_uses_minion_ability_damage(self):
        g=self.game((PAGETURNER,),board=(TEST+'bonus',));source=self.play(g,PAGETURNER)
        self.assertEqual(self.hero(g,2).health,27)
        self.assertEqual([e.amount for e in g.events if e.kind=='damage_dealt'and e.source_id==source],[3])

    def test_pageturner_initial_scenario_body_has_no_fabricated_summon(self):
        g=self.game(board=(PAGETURNER,));g.apply(EndTurn(1))
        self.assertEqual(self.hero(g,2).health,30)
        self.assertFalse(g.state.successful_summon_history)

    def test_pageturner_own_elemental_and_all_each_count_one_actual_summon(self):
        for cid in(TEST+'elemental',TEST+'all',TEST+'dormant'):
            g=self.game((cid,),board=(PAGETURNER,));self.play(g,cid)
            self.assertEqual(self.hero(g,2).health,27)

    def test_pageturner_opponent_non_elemental_and_transform_do_not_create_qualified_summon(self):
        g=self.game((TEST+'plain',TEST+'transform'),board=(PAGETURNER,));source=self.play(g,TEST+'plain')
        self.play(g,TEST+'transform',source);self.assertEqual(self.hero(g,2).health,30)
        h=self.game(board=(PAGETURNER,),enemy_hand=(TEST+'elemental',),active=2);self.play(h,TEST+'elemental')
        self.assertEqual(self.hero(h,2).health,30)

    def test_pageturner_uses_current_submitted_summon_tribes_and_excludes_changed_away(self):
        g=self.game((TEST+'elementalize',TEST+'plain'),board=(PAGETURNER,));self.play(g,TEST+'elementalize');self.play(g,TEST+'plain')
        self.assertEqual(self.hero(g,2).health,27)
        h=self.game((TEST+'unelemental',TEST+'elemental'),board=(PAGETURNER,));self.play(h,TEST+'unelemental');self.play(h,TEST+'elemental')
        self.assertEqual(self.hero(h,2).health,30)

    def test_pageturner_unknown_own_summon_tribes_fail_atomically(self):
        g=self.game((TEST+'unknown',),board=(PAGETURNER,));saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Unknown original Elemental summon tribes'):self.play(g,TEST+'unknown')
        self.assertEqual(g.snapshot(),saved)

    def test_pageturner_one_weight_per_live_enemy_and_expected_rng(self):
        g=self.game((TEST+'elemental',),board=(PAGETURNER,),enemy=(YETI,),seed=7)
        state=g.snapshot()['rng_state'];rng=Random();rng.setstate((state[0],tuple(state[1]),state[2]))
        target=rng.choice(sorted((self.hero(g,2).id,self.first(g,YETI,2).id)))
        self.play(g,TEST+'elemental')
        choice=next(e for e in g.events if e.kind=='random_choice')
        self.assertEqual(choice.target_id,target)
        self.assertEqual(g.snapshot()['rng_state'],[rng.getstate()[0],list(rng.getstate()[1]),rng.getstate()[2]])

    def test_pageturner_later_match_requeries_enemy_after_first_target_dies(self):
        g=self.game((TEST+'double',),board=(PAGETURNER,),enemy=(TEST+'frail',),seed=0)
        target=self.first(g,TEST+'frail',2).id;self.play(g,TEST+'double')
        choices=[e.target_id for e in g.events if e.kind=='random_choice']
        self.assertEqual(choices,[target,self.hero(g,2).id]);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)

    def test_pageturner_accepted_notification_survives_source_death_from_earlier_reaction(self):
        g=self.game((TEST+'elemental',),board=(TEST+'early_remove',PAGETURNER))
        source=self.first(g,PAGETURNER).id;self.play(g,TEST+'elemental')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(self.hero(g,2).health,27)

    def test_pageturner_silence_removes_future_listener_and_dormant_enemies_are_not_selected(self):
        g=self.game((TEST+'silence',TEST+'elemental'),board=(PAGETURNER,))
        self.play(g,TEST+'silence',self.first(g,PAGETURNER).id);self.play(g,TEST+'elemental')
        self.assertEqual(self.hero(g,2).health,30)
        h=self.game((TEST+'elemental',),board=(PAGETURNER,),enemy=(TEST+'dormant',));self.play(h,TEST+'elemental')
        self.assertEqual(self.hero(h,2).health,27);self.assertEqual(self.first(h,TEST+'dormant',2).health,4)

    def test_pageturner_damage_choice_restore_failure_keeps_one_actual_hit(self):
        g=self.game((TEST+'elemental',),board=(PAGETURNER,TEST+'damage_wait'));self.play(g,TEST+'elemental')
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.hero(g,2).health,27);self.portable(g)


if __name__=='__main__':unittest.main()
