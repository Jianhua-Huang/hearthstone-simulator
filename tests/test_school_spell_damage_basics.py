"""Native school Spell Damage feeds original numeric packets and split budgets."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, DamageKind, EndTurn,
    Game, PlayCard, PlayerSetup, Rarity, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, SpellSchool, Zone, RandomSplitDamage, SplitDamageScope)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Damage,
    DamageBatch, Destroy, GrantSpellDamage, Heal, InvokeBehavior, RequestChoice,
    ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.health_rules import (spell_bonus, spell_damage_sources,
    validate_school_spell_damage_carrier)
from hs_sim.engine.model import AbilityInstance
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

BRUKAN='BAR_048'
PATH=Path(__file__).resolve().parents[1]/'data/support/school-spell-damage-basics.json'
PIN='18c80caec36fd68683053ff3a96887cf885800d6b986cff1e4f7a32cdf7caf51'
NATURE=(SpellSchool.NATURE,)

def evidence():
    support=json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support)!=PIN:raise ValueError('School evidence changed')
    for row in support['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw card evidence changed')
    return support['records'][0]['data']

def registry():
    r=Registry('isolated-school-spell-damage-basics-v1');raw=evidence()
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition(BRUKAN,raw['name'],CardType.MINION,cost=raw['cost'],
        attack=raw['attack'],health=raw['health'],spell_damage=3,spell_damage_schools=NATURE,
        metadata=metadata(CardClass.SHAMAN,rarity=Rarity.LEGENDARY)))
    for cid,bonus,schools in (('plain',0,()),('universal',2,()),('fire-provider',1,(SpellSchool.FIRE,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=2,health=8,
            spell_damage=bonus,spell_damage_schools=schools,metadata=metadata()))
    r.register_behavior('noop',lambda c:())
    r.register_card(CardDefinition('weapon','Weapon',CardType.WEAPON,attack=1,durability=2,metadata=metadata()))
    def provider(c):return next(i for i in c.state.players[1].board if c.state.entities[i].card_id==BRUKAN)
    def fail(c):raise ValueError('Fixture late failure')
    r.register_behavior('late-fault',fail)
    def wait(c):
        root=next(v for v in c.state.split_damage_history if v.request.source_id==c.source_id)
        if len(root.packets)!=1:return ()
        source=provider(c)
        return (RequestChoice(c.player_id,(
            ChoiceOption('silence','Remove provider',(Silence(source),)),
            ChoiceOption('fault','Remove and fail',(Silence(source),InvokeBehavior('late-fault',source_id=c.source_id,player_id=c.player_id))),
        ),c.source_id),)
    r.register_behavior('wait-first',wait)
    for school in (*SpellSchool,None):
        name=school.value if school is not None else 'untyped'
        def hit(c):return (Damage(c.target_id,2,c.source_id,DamageKind.SPELL),)
        r.register_behavior(name,hit)
        r.register_card(CardDefinition(name,name,CardType.SPELL,cost=1,on_play=name,requires_target=True,
            spell_school=school,metadata=metadata()))
    def split(c,wait=False):return (RandomSplitDamage(c.player_id,c.cast.id,c.source_id,2,
        SplitDamageScope('enemy',(CardType.HERO,)),on_result='wait-first' if wait else None),)
    for name,school,body,targeted in (
        ('split-nature',SpellSchool.NATURE,split,False),
        ('split-fire',SpellSchool.FIRE,split,False),('split-untyped',None,split,False),
        ('split-wait',SpellSchool.NATURE,lambda c:split(c,True),False),
        ('aoe',SpellSchool.NATURE,lambda c:(DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.SPELL)
            for i in (*c.state.players[2].board,c.state.players[2].hero_id))),),False),
        ('self-batch',SpellSchool.NATURE,lambda c:(DamageBatch((Damage(provider(c),4,c.source_id,DamageKind.SPELL),
            Damage(c.state.players[2].hero_id,2,c.source_id,DamageKind.SPELL))),),False),
        ('effect-hit',SpellSchool.NATURE,lambda c:(Damage(c.target_id,2,c.source_id),),True),
        ('healing',SpellSchool.NATURE,lambda c:(Heal(c.target_id,2,c.source_id),),True),
        ('silence',None,lambda c:(Silence(c.target_id),),True),
        ('destroy',None,lambda c:(Destroy(c.target_id,c.source_id),),True),
        ('bounce',None,lambda c:(ReturnToHand(c.target_id),),True),
        ('transform',None,lambda c:(Transform(c.target_id,'plain'),),True),
        ('brukan-face',None,lambda c:(Transform(c.target_id,BRUKAN),),True),
        ('copy',None,lambda c:(CopyMinion(c.target_id,c.player_id),),True),
        ('base-copy',None,lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),True),
        ('transfer',None,lambda c:(ChangeControl(c.target_id,2),),True),
        ('sleep',None,lambda c:(MakeDormant(c.target_id,None),),True),
        ('wake',None,lambda c:(AwakenMinion(provider(c)),),False),
        ('summon-brukan',None,lambda c:(Summon(c.player_id,BRUKAN),),False),
        ('grant-flat',None,lambda c:(GrantSpellDamage(c.target_id,2,c.source_id),),True),
        ('fault',None,lambda c:(Silence(c.target_id),InvokeBehavior('late-fault',source_id=c.source_id,player_id=c.player_id)),True),
    ):
        r.register_behavior(name,body);r.register_card(CardDefinition(name,name,CardType.SPELL,cost=0,on_play=name,
            requires_target=targeted,spell_school=school,metadata=metadata()))
    return r

class SchoolSpellDamageBasicsTests(unittest.TestCase):
    def game(self,hand=('nature',),board=(BRUKAN,),enemy=(),enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*4,mana=10,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=enemy,deck=('plain',)*4,mana=10,max_mana=10),
        ),seed=41),registry())
    def source(self,g):return next(i for i in g.state.players[1].board if g.state.entities[i].card_id==BRUKAN)
    def hero(self,g,p=2):return g.state.players[p].hero_id
    def play(self,g,cid='nature',target=None):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,target if g.registry.card(cid).requires_target else None));return eid
    def bonus(self,g,school=SpellSchool.NATURE,p=1):return spell_bonus(g.state,p,g.registry,school)
    def choose(self,g,key='silence'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def roundtrip(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,registry()).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),registry()).snapshot(),snap)
    def rehash(self,snap):
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')});return snap
    def ability_row(self,snap,eid):return next(a for a in snap['state']['entities'][str(eid)]['abilities'] if a['kind']=='spell_damage')

    def test_raw_pin_native_amount_and_school_not_presence_tag_value(self):
        raw=evidence();self.assertEqual((raw['id'],raw['dbf_id'],raw['cost'],raw['attack'],raw['health']),(BRUKAN,63074,4,5,4))
        self.assertEqual(raw['text_en'],'<b>Nature Spell Damage +3</b>');self.assertEqual(raw['tags']['SPELLPOWER_NATURE'],1)
        card=registry().card(BRUKAN);self.assertEqual((card.spell_damage,card.spell_damage_schools),(3,NATURE))

    def test_selector_requires_unique_immutable_exact_schools(self):
        base=CardDefinition('test','Test',CardType.MINION,health=4,spell_damage=3)
        self.assertEqual(base.spell_damage_schools,())
        for value in (None,[],['nature'],'nature',('nature',),(True,),NATURE*2):
            with self.subTest(value=value),self.assertRaises(ValueError):Registry('bad').register_card(replace(base,spell_damage_schools=value))

    def test_nonempty_native_declaration_requires_positive_ordinary_minion(self):
        card=registry().card(BRUKAN)
        for fields in ({'spell_damage':0},{'kind':CardType.HERO},{'kind':CardType.WEAPON},
            {'kind':CardType.SPELL},{'starship_for':CardClass.SHAMAN}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):Registry('bad').register_card(replace(card,**fields))

    def test_school_ability_requires_native_removable_unconsumed_provenance(self):
        a=AbilityInstance(1,'spell_damage',source_id=2,origin='printed',spell_damage=3,spell_damage_schools=NATURE)
        self.assertEqual(AbilityInstance(2,'spell_damage',spell_damage=1).spell_damage_schools,())
        for fields in ({'origin':'granted'},{'source_id':None},{'expires_turn':1},{'consumed':True},
            {'remove_on_silence':False},{'magnetic_id':3},{'spell_damage':0},{'kind':'on_play'}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):replace(a,**fields)

    def test_complete_native_amount_selector_and_quantity_are_checked(self):
        g=self.game();a=next(a for a in g.state.entities[self.source(g)].abilities if a.kind=='spell_damage')
        for abilities in ((replace(a,spell_damage_schools=()),),(replace(a,spell_damage=2),),
            (replace(a,spell_damage_schools=(SpellSchool.FIRE,)),),(a,replace(a,id=999)),):
            with self.subTest(abilities=abilities),self.assertRaises(ValueError):
                validate_school_spell_damage_carrier(g.registry,BRUKAN,CardType.MINION,abilities)

    def test_current_school_filter_and_original_aggregate_query_share_provider_order(self):
        g=self.game(board=(BRUKAN,'universal','fire-provider'))
        self.assertEqual(spell_bonus(g.state,1,g.registry),6)
        self.assertEqual([self.bonus(g,s) for s in (SpellSchool.NATURE,SpellSchool.FIRE,None)], [5,3,2])
        rows=spell_damage_sources(g.state,1,g.registry,SpellSchool.NATURE)
        self.assertEqual([r[3] for r in rows],[3,2]);self.assertEqual([r[0].card_id for r in rows],[BRUKAN,'universal'])
        for school in ('nature',True,1,()):
            with self.subTest(school=school),self.assertRaises(ValueError):self.bonus(g,school)

    def test_nature_spell_receives_three_bonus_and_one_original_payment(self):
        g=self.game();source=self.play(g,target=self.hero(g))
        self.assertEqual(g.state.entities[self.hero(g)].health,75);self.assertEqual(g.state.players[1].mana,9)
        result=next(v for e in g.events if (v:=health_result(e)) is not None and v.source_id==source)
        self.assertEqual((result.base_amount,result.spell_bonus,result.modified_amount),(2,3,5))

    def test_other_schools_and_explicit_untyped_spell_do_not_receive_nature_bonus(self):
        names=tuple(s.value for s in SpellSchool if s!=SpellSchool.NATURE)+('untyped',)
        g=self.game(hand=names)
        for name in names:self.play(g,name,self.hero(g))
        self.assertEqual(g.state.entities[self.hero(g)].health,80-2*len(names))

    def test_ordinary_spell_damage_still_applies_to_matching_other_and_untyped(self):
        g=self.game(hand=('nature','fire','untyped'),board=(BRUKAN,'universal'))
        for name in ('nature','fire','untyped'):self.play(g,name,self.hero(g))
        self.assertEqual(g.state.entities[self.hero(g)].health,65)

    def test_multiple_physical_native_sources_each_contribute_once(self):
        g=self.game(board=(BRUKAN,BRUKAN));self.play(g,target=self.hero(g))
        self.assertEqual(g.state.entities[self.hero(g)].health,72);self.assertEqual(self.bonus(g),6)

    def test_enemy_provider_does_not_contribute_to_caster(self):
        g=self.game(board=(),enemy=(BRUKAN,));self.play(g,target=self.hero(g))
        self.assertEqual(g.state.entities[self.hero(g)].health,78)

    def test_hand_and_deck_native_sources_are_not_live_providers(self):
        g=self.game(hand=(BRUKAN,'nature'),board=());self.play(g,target=self.hero(g))
        self.assertEqual(self.bonus(g),0);self.assertEqual(g.state.entities[self.hero(g)].health,78)

    def test_nonspell_effect_damage_does_not_receive_school_or_ordinary_bonus(self):
        g=self.game(hand=('effect-hit',),board=(BRUKAN,'universal'));self.play(g,'effect-hit',self.hero(g))
        self.assertEqual(g.state.entities[self.hero(g)].health,78)

    def test_normal_healing_uses_existing_healing_path_without_bonus(self):
        g=self.game(hand=('effect-hit','healing'));self.play(g,'effect-hit',self.hero(g,1));self.play(g,'healing',self.hero(g,1))
        self.assertEqual(g.state.entities[self.hero(g,1)].health,80)

    def test_aoe_receives_bonus_per_original_damage_packet(self):
        g=self.game(hand=('aoe',),enemy=('plain','plain'));targets=tuple(g.state.players[2].board);self.play(g,'aoe')
        self.assertEqual([g.state.entities[i].health for i in targets],[3,3])
        self.assertEqual(g.state.entities[self.hero(g)].health,75)

    def test_original_batch_freezes_school_bonus_when_provider_dies_in_first_packet(self):
        g=self.game(hand=('self-batch',));source=self.source(g);self.play(g,'self-batch')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[self.hero(g)].health,75);self.assertEqual(self.bonus(g),0)

    def test_split_accepts_three_bonus_once_then_delivers_five_unit_packets(self):
        g=self.game(hand=('split-nature',));self.play(g,'split-nature');root=g.state.split_damage_history[0]
        self.assertEqual((root.quote.spell_bonus,root.quote.budget,len(root.packets)),(3,5,5))
        self.assertEqual(g.state.entities[self.hero(g)].health,75)
        values=[v for e in g.events if (v:=health_result(e)) is not None and v.split_packet is not None]
        self.assertEqual([(v.base_amount,v.spell_bonus,v.modified_amount) for v in values],[(1,0,1)]*5)
        self.assertEqual(root.quote.contributions[0].ability.spell_damage_schools,NATURE);self.roundtrip(g)

    def test_other_school_and_untyped_split_exclude_nature_contributor(self):
        g=self.game(hand=('split-fire','split-untyped'))
        for name in ('split-fire','split-untyped'):self.play(g,name)
        self.assertEqual([(r.quote.spell_bonus,r.quote.budget,r.quote.contributions) for r in g.state.split_damage_history],[(0,2,()),(0,2,())])
        self.assertEqual(g.state.entities[self.hero(g)].health,76)

    def test_split_shared_provider_match_includes_unrestricted_contribution(self):
        g=self.game(hand=('split-nature',),board=(BRUKAN,'universal'));self.play(g,'split-nature')
        root=g.state.split_damage_history[0];self.assertEqual((root.quote.spell_bonus,root.quote.budget),(5,7))
        self.assertEqual([c.amount for c in root.quote.contributions],[3,2])

    def test_native_play_and_summon_initialize_same_school_ability(self):
        g=self.game(hand=(BRUKAN,'summon-brukan'),board=());self.play(g,BRUKAN);self.play(g,'summon-brukan')
        self.assertEqual(self.bonus(g),6)
        self.assertEqual([a.spell_damage_schools for i in g.state.players[1].board for a in g.state.entities[i].abilities if a.kind=='spell_damage'],[NATURE,NATURE])

    def test_silence_removes_native_school_contribution(self):
        g=self.game(hand=('silence','nature'));self.play(g,'silence',self.source(g));self.play(g,target=self.hero(g))
        self.assertEqual(self.bonus(g),0);self.assertEqual(g.state.entities[self.hero(g)].health,78)

    def test_destroy_preserves_frozen_native_school_declaration(self):
        g=self.game(hand=('destroy','nature'));source=self.source(g);self.play(g,'destroy',source);self.play(g,target=self.hero(g))
        self.assertEqual(g.state.entities[self.hero(g)].health,78)
        record=next(r for r in g.state.death_history if r.entity_id==source)
        self.assertEqual(next(a.spell_damage_schools for a in record.abilities if a.kind=='spell_damage'),NATURE);self.roundtrip(g)

    def test_bounce_removes_live_contribution_and_native_replay_restores_it(self):
        g=self.game(hand=('bounce',));source=self.source(g);self.play(g,'bounce',source)
        self.assertEqual(self.bonus(g),0);self.play(g,BRUKAN);self.assertEqual(self.bonus(g),3)

    def test_transform_away_and_into_native_source_use_original_reset(self):
        g=self.game(hand=('transform','brukan-face'));source=self.source(g);self.play(g,'transform',source)
        self.assertEqual(self.bonus(g),0);self.play(g,'brukan-face',source);self.assertEqual(self.bonus(g),3)

    def test_control_change_moves_contribution_to_current_controller(self):
        g=self.game(hand=('transfer',));self.play(g,'transfer',self.source(g))
        self.assertEqual((self.bonus(g,p=1),self.bonus(g,p=2)),(0,3));self.roundtrip(g)

    def test_current_and_base_copies_both_preserve_native_school_declaration(self):
        g=self.game(hand=('copy','base-copy'));source=self.source(g);self.play(g,'copy',source);self.play(g,'base-copy',source)
        self.assertEqual(self.bonus(g),9);self.assertEqual(len(g.state.players[1].board),3);self.roundtrip(g)

    def test_current_copy_of_silenced_source_stays_silenced_base_copy_is_native(self):
        g=self.game(hand=('silence','copy','base-copy'));source=self.source(g);self.play(g,'silence',source)
        self.play(g,'copy',source);self.assertEqual(self.bonus(g),0);self.play(g,'base-copy',source);self.assertEqual(self.bonus(g),3)

    def test_dormancy_and_awaken_use_existing_live_provider_eligibility(self):
        g=self.game(hand=('sleep','wake'));self.play(g,'sleep',self.source(g));self.assertEqual(self.bonus(g),0)
        self.play(g,'wake');self.assertEqual(self.bonus(g),3)

    def test_existing_unrestricted_grant_remains_separate_from_native_selector(self):
        g=self.game(hand=('grant-flat','fire'));self.play(g,'grant-flat',self.source(g));self.play(g,'fire',self.hero(g))
        self.assertEqual(g.state.entities[self.hero(g)].health,76);self.assertEqual(self.bonus(g),5)

    def test_natural_end_does_not_expire_native_school_declaration(self):
        g=self.game();g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(self.bonus(g),3);self.roundtrip(g)

    def test_waiting_split_keeps_original_budget_after_provider_silence_and_recovers(self):
        g=self.game(hand=('split-wait',));self.play(g,'split-wait');self.assertIsNotNone(g.state.pending_choice)
        self.roundtrip(g);restored=Game.from_snapshot(g.snapshot(),registry());self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.bonus(g),0)
        self.assertEqual((g.state.split_damage_history[0].quote.budget,len(g.state.split_damage_history[0].packets)),(5,5))
        self.assertEqual(g.state.entities[self.hero(g)].health,75);self.roundtrip(g)

    def test_failed_waiting_split_choice_rolls_back_without_requoting_or_redrawing(self):
        g=self.game(hand=('split-wait',));self.play(g,'split-wait');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(g.state.entities[self.hero(g)].health,75)

    def test_immediate_failure_after_source_removal_rolls_back(self):
        g=self.game(hand=('fault',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'fault',self.source(g))
        self.assertEqual(g.snapshot(),before)

    def test_queries_and_player_projection_are_pure_without_private_provider_proofs(self):
        g=self.game(hand=('split-wait',));before=g.snapshot()
        for p in (1,2):
            self.bonus(g,p=p);spell_bonus(g.state,p,g.registry);g.for_player(p).legal_actions()
            text=json.dumps(g.for_player(p).observe())
            for key in ('abilities','source_json','rng_state','spell_damage_schools','contributions'):
                self.assertNotIn('"'+key+'"',text)
        self.assertEqual(g.snapshot(),before)

    def test_rehashed_snapshot_rejects_missing_wrong_or_stripped_selector(self):
        g=self.game();source=self.source(g)
        for value in (None,[],['unknown'],['nature','nature'],['fire']):
            snap=g.snapshot();self.ability_row(snap,source)['spell_damage_schools']=value
            with self.subTest(value=value),self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(snap),registry())
        snap=g.snapshot();self.ability_row(snap,source).pop('spell_damage_schools')
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(snap),registry())

    def test_death_record_native_selector_is_checked_against_original_card(self):
        g=self.game(hand=('destroy',));self.play(g,'destroy',self.source(g));snap=g.snapshot()
        next(a for a in snap['state']['death_history'][0]['abilities'] if a['kind']=='spell_damage')['spell_damage_schools']=[]
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(snap),registry())

    def test_captured_rule_context_checks_selector_in_its_own_state(self):
        g=self.game();source=self.source(g);codec=FrameCodec(g.mechanics,g.registry)
        context=RuleContext(g.state,source,1);encoded=codec.encode(context);self.assertEqual(codec.decode(encoded),context)
        self.ability_row({'state':encoded['fields']['state']['state']},source)['spell_damage_schools']=[]
        with self.assertRaises(ValueError):codec.decode(encoded)

    def test_original_split_quote_rejects_wrong_school_contribution(self):
        g=self.game(hand=('split-nature',));self.play(g,'split-nature');quote=g.state.split_damage_history[0].quote
        with self.assertRaises(ValueError):replace(quote,school=SpellSchool.FIRE)
        with self.assertRaises(ValueError):replace(quote,school=None)

    def test_closed_split_original_provider_selector_survives_later_silence(self):
        g=self.game(hand=('split-nature','silence'));self.play(g,'split-nature');self.play(g,'silence',self.source(g));self.roundtrip(g)
        self.assertEqual(g.state.split_damage_history[0].quote.contributions[0].ability.spell_damage_schools,NATURE)

    def test_current_versions_and_all_previous_schemas_are_strict(self):
        g=self.game();snap=g.snapshot();self.assertEqual(snap['schema_version'],265)
        self.assertEqual(snap['ruleset']['id'],'prototype-v302');self.assertEqual(snap['mechanics_version']['version'],CORE_EFFECTS_VERSION)
        for schema in (*range(1,218),None,True,189.0,'189',217):
            bad=deepcopy(snap);bad['schema_version']=schema
            with self.subTest(schema=schema),self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
