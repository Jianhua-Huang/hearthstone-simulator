"""Real Primus skills, Rune discoveries and an original native spell programme."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import primus_titan as native
from hs_sim.engine import (CardClass,CardDefinition,CardType,EndTurn,Game,IllegalAction,Keyword,
    PlayCard,PlayerSetup,ResolutionError,Scenario,SnapshotError,TriggerSpec,UseMinionAbility)
from hs_sim.engine.allocation_facts import SourceAllocationFact,allocation_from_dict
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Damage,Destroy,InvokeBehavior,
    RequestChoice,Silence,Transform)
from hs_sim.engine.health_rules import spell_bonus
from hs_sim.engine.minion_abilities import remaining_abilities
from hs_sim.engine.model import CardMetadata,DamageKind,Rarity,Runes,TargetSpec,Zone
from hs_sim.engine.next_spell_bonuses import INSTALLED,validate_ability_origin
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION,canonical_hash,event_from_dict
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P='k611.'
PLAIN,NOOP,WOUND,KILL,CHANGE,WAIT,FAIL,AUTO=(P+x for x in('plain','noop','wound','kill','change','wait','fail','auto'))
FROSTBOLT,COUNTER='CS2_024','EX1_287'
RUNE_IDS={rune:tuple(P+rune+str(i)for i in range(3))for rune in('blood','frost','unholy')}
UNKNOWN=P+'unknown_frost'
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


def context():return GenerationContext(P+'explicit-full','experimental')


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=build_registry();r.register_behavior(NOOP,lambda c:())
    r.register_card(CardDefinition(NOOP,NOOP,CardType.SPELL,on_play=NOOP))
    r.register_card(CardDefinition(PLAIN,PLAIN,CardType.MINION,cost=1,attack=2,health=8,metadata=META))
    r.register_pool_card(PoolCard.from_definition(r.card(PLAIN)))
    members=[PLAIN]
    for rune,ids in RUNE_IDS.items():
        for cid in ids:
            meta=replace(META,classes=(CardClass.DEATH_KNIGHT,),runes=Runes(**{rune:1}))
            r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=4,attack=2,health=3,metadata=meta))
            r.register_pool_card(PoolCard.from_definition(r.card(cid)));members.append(cid)
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,4,replace(META,classes=(CardClass.DEATH_KNIGHT,),runes=Runes(frost=1))))
        members.append(UNKNOWN)
    if mode=='empty':members=[PLAIN]
    def fail(c):raise ResolutionError('K611 deliberate native failure')
    r.register_behavior(FAIL,fail)
    def watch(c):
        event=c.event
        if c.state.entities[event.source_id].card_id!=native.CARD:return ()
        return(RequestChoice(c.player_id,(
            ChoiceOption('continue','Continue'),
            ChoiceOption('kill','Destroy original',(Destroy(event.source_id,c.source_id),)),
            ChoiceOption('transform','Transform original',(Transform(event.source_id,PLAIN),)),
            ChoiceOption('control','Change controller',(ChangeControl(event.source_id,3-event.player_id),)),
            ChoiceOption('silence','Silence original',(Silence(event.source_id),)),
            ChoiceOption('fail','Fail',(InvokeBehavior(FAIL,c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(WAIT,watch)
    r.register_card(CardDefinition(WAIT,WAIT,CardType.MINION,health=15,triggers=(TriggerSpec('minion_ability_started',WAIT),)))
    scripts={WOUND:lambda c:(Damage(c.target_id,3,c.source_id),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),CHANGE:lambda c:(Transform(c.target_id,PLAIN),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.MINION if cid==CHANGE else CardType.SPELL,
            **({'battlecry':cid,'health':1}if cid==CHANGE else {'on_play':cid}),
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,FROSTBOLT,c.source_id,c.state.players[3-c.player_id].hero_id,targeting='explicit'),))
    r.register_card(CardDefinition(AUTO,AUTO,CardType.MINION,health=1,battlecry=AUTO))
    r.register_pool(PoolDefinition(native.POOL,P+'complete-v1',context().target_id,'experimental',tuple(PoolMember(cid)for cid in members),complete=True))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    return s


class PrimusTitanTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'

    def game(self,hand=(),*,board=(),enemy_board=(),enemy_hand=(),player=1,active=None,mode='normal'):
        self.mode=mode
        setups=tuple(PlayerSetup('HERO_08',hand=hand if p==player else enemy_hand,
            board=board if p==player else enemy_board,deck=(NOOP,)*5,mana=30,max_mana=30,mana_cap=30)for p in(1,2))
        return Game.from_scenario(Scenario(setups,active_player=active or player,seed=611,generation_context=context()),registry(mode))

    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]

    def use(self,g,skill,target=None,player=1):
        source=self.entity(g,native.CARD,player,'board').id
        mana=g.state.players[player].mana;casts=len(g.state.cast_history)
        g.apply(UseMinionAbility(player,source,skill,target))
        self.assertEqual(g.state.players[player].mana,mana);self.assertEqual(len(g.state.cast_history),casts)
        return source

    def discover(self,g,rune):
        choice=g.state.pending_choice
        self.assertIsNotNone(choice)
        self.assertEqual({o.card_id for o in choice.options},set(RUNE_IDS[rune]))
        cid=choice.options[0].card_id;self.choose(g,choice.options[0].id)
        return cid

    def pending(self,g,p=1):return tuple(e for e in g.state.players[p].player_effects if e.spec_id==native.SPEC)

    def proof(self,g):
        event=next(e for e in g.events if e.kind==INSTALLED and 'ability_event_json'in dict(e.data))
        data=dict(event.data)
        return event,event_from_dict(json.loads(data['ability_event_json'])),allocation_from_dict(json.loads(data['ability_source_json']))

    def test_seven_full_rows_fourteen_primary_faces_three_nonphysical_skills_and_original_token(self):
        d=native.load_batch();rows={r['record']['id']:r for k in('cards','dependencies','existing_dependencies','evidence_only')for r in d[k]}
        self.assertEqual((len(rows),len(d['official_observations'])),(7,14))
        for obs in d['official_observations']:batch.check_face(rows[obs['card_id']]['record'],obs['face'],obs['locale'],numeric_normalizations=d['numeric_normalizations'].get(obs['card_id']))
        for cid in native.SKILLS:
            card=registry().card(cid);self.assertTrue(card.choice_only);self.assertFalse(card.hand_playable);self.assertNotIn(cid,registry().pool_cards)
            self.assertIsNone(rows[cid]['record']['cost']);self.assertEqual(card.cost,0)
        row=d['existing_dependencies'][0];self.assertEqual(batch.canonical(asdict(registry().card(native.TOKEN))),row['definition_sha256'])
        self.assertFalse(d['new_token_ids']);self.assertEqual(native.COLLECTIBLE_ROOTS,());self.assertFalse(d['formal_pool_complete'])

    def test_paid_primus_blood_uses_remaining_enemy_health_for_self_and_hero_both_seats(self):
        for player in(1,2):
            g=self.game((native.CARD,WOUND),enemy_board=(PLAIN,),player=player)
            self.play(g,native.CARD,player=player);self.assertEqual(g.state.players[player].mana,22)
            victim=self.entity(g,PLAIN,3-player,'board').id;self.play(g,WOUND,victim,player)
            source=self.use(g,native.BLOOD,victim,player)
            self.assertEqual((g.state.entities[source].health,g.state.entities[source].max_health),(14,14))
            self.assertEqual((self.hero(g,player).health,self.hero(g,player).max_health),(35,35))
            self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD);self.discover(g,'blood')
            self.assertEqual(len(remaining_abilities(g.state.entities[source])),2)

    def test_blood_rejects_missing_friendly_and_hero_targets_without_consuming_skill(self):
        g=self.game(board=(native.CARD,PLAIN));before=g.snapshot();source=self.entity(g,native.CARD,zone='board').id
        for target in(None,self.hero(g,2).id,self.entity(g,PLAIN,zone='board').id):
            with self.assertRaises(IllegalAction):g.apply(UseMinionAbility(1,source,native.BLOOD,target))
            self.assertEqual(g.snapshot(),before)

    def test_blood_source_killed_before_body_still_destroys_original_enemy_and_grants_hero_health(self):
        g=self.game(board=(native.CARD,WAIT),enemy_board=(PLAIN,));victim=self.entity(g,PLAIN,2,'board').id
        source=self.use(g,native.BLOOD,victim);self.choose(g,'kill')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD)
        self.assertEqual(self.hero(g).max_health,38);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_unholy_summons_two_existing_taunt_reborn_servants_with_real_death_rebirth(self):
        g=self.game((KILL,),board=(native.CARD,));self.use(g,native.UNHOLY);self.discover(g,'unholy')
        servants=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==native.TOKEN]
        self.assertEqual(len(servants),2)
        for e in servants:self.assertEqual((e.attack,e.health),(3,3));self.assertTrue({Keyword.TAUNT,Keyword.REBORN}<=e.keywords)
        self.assertEqual(len(g.state.card_summon_history),2)
        self.play(g,KILL,servants[0].id)
        fresh=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==native.TOKEN and i not in {e.id for e in servants}]
        self.assertEqual(len(fresh),1);self.assertEqual((fresh[0].attack,fresh[0].health),(3,1));self.assertNotIn(Keyword.REBORN,fresh[0].keywords)
        self.portable(g)

    def test_unholy_respects_actual_remaining_board_space_without_losing_rune_discovery(self):
        for copies,expected in((5,1),(6,0)):
            g=self.game(board=(native.CARD,)+(PLAIN,)*copies);self.use(g,native.UNHOLY);self.discover(g,'unholy')
            self.assertEqual(sum(g.state.entities[i].card_id==native.TOKEN for i in g.state.players[1].board),expected)

    def test_frost_paid_spell_owns_exact_pair_without_ambient_damage_and_only_first_cast_both_seats(self):
        for player in(1,2):
            g=self.game((native.CARD,FROSTBOLT,FROSTBOLT),player=player);self.play(g,native.CARD,player=player)
            self.use(g,native.FROST,player=player);self.discover(g,'frost');bonus=self.pending(g,player)[0]
            self.assertEqual(spell_bonus(g.state,player,g.registry),0)
            self.assertEqual(quote_cost(g.state,g.registry,self.entity(g,FROSTBOLT,player)).amount,0)
            self.play(g,FROSTBOLT,self.hero(g,3-player).id,player)
            self.assertEqual((self.hero(g,3-player).health,g.state.players[player].mana),(24,22))
            self.assertEqual(g.state.cast_history[-1].next_spell_bonus_effects,(bonus,));self.assertFalse(self.pending(g,player))
            self.play(g,FROSTBOLT,self.hero(g,3-player).id,player);self.assertEqual(self.hero(g,3-player).health,21)
            self.portable(g)

    def test_ability_and_rune_waits_restore_independently_without_repayment_or_duplicate_bonus(self):
        g=self.game((FROSTBOLT,),board=(native.CARD,WAIT));source=self.use(g,native.FROST)
        restored=self.portable(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K611 deliberate'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(len(self.pending(g)),1)
        restored=self.portable(g);choice=g.state.pending_choice;selected=choice.options[0].id
        self.choose(g,selected);self.choose(restored,selected);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(g.state.entities[source].attacks_this_turn,1);self.play(g,FROSTBOLT,self.hero(g,2).id)
        self.assertEqual(self.hero(g,2).health,24);self.portable(g)

    def test_original_native_frost_bonus_keeps_original_player_when_source_dies_transforms_changes_control_or_silences_before_body(self):
        for operation in('kill','transform','control','silence'):
            g=self.game((FROSTBOLT,),board=(native.CARD,WAIT));source=self.use(g,native.FROST);self.choose(g,operation)
            if g.state.pending_choice:self.choose(g,g.state.pending_choice.options[0].id)
            self.assertEqual((len(self.pending(g,1)),len(self.pending(g,2))),(1,0))
            event,origin,fact=self.proof(g);self.assertEqual((fact.entity_id,fact.card_id,fact.controller,fact.zone),(source,native.CARD,1,Zone.BOARD))
            self.assertLess(origin.action,event.action);self.portable(g)
            self.play(g,FROSTBOLT,self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,24)

    def test_installed_pair_survives_source_transform_and_owner_turns(self):
        g=self.game((CHANGE,FROSTBOLT),board=(native.CARD,));source=self.use(g,native.FROST);self.discover(g,'frost')
        self.play(g,CHANGE,source);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(len(self.pending(g)),1);self.assertEqual(g.state.entities[source].card_id,PLAIN);self.portable(g)
        self.play(g,FROSTBOLT,self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,24)

    def test_automatic_spell_from_nonspell_claims_paired_bonus_once(self):
        g=self.game((AUTO,FROSTBOLT),board=(native.CARD,));self.use(g,native.FROST);self.discover(g,'frost')
        bonus=self.pending(g)[0];self.play(g,AUTO)
        self.assertEqual(self.hero(g,2).health,24);self.assertFalse(self.pending(g));self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual((g.state.cast_history[-1].origin,g.state.cast_history[-1].next_spell_bonus_effects),('effect',(bonus,)))
        self.portable(g)

    def test_countered_spell_consumes_pair_under_existing_paid_admission_policy(self):
        g=self.game((FROSTBOLT,),board=(native.CARD,),enemy_hand=(COUNTER,),active=2)
        self.play(g,COUNTER,player=2);g.apply(EndTurn(2));self.use(g,native.FROST);self.discover(g,'frost')
        self.play(g,FROSTBOLT,self.hero(g,2).id)
        self.assertEqual(self.hero(g,2).health,30);self.assertFalse(self.pending(g));self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual(g.state.cast_history[-1].failure,'countered');self.portable(g)

    def test_rune_discoveries_preserve_full_candidate_identity_and_ignore_current_mage_class(self):
        for skill,rune in native.RUNE_BY_SKILL.items():
            g=self.game(board=(native.CARD,),enemy_board=(PLAIN,))
            target=self.entity(g,PLAIN,2,'board').id if skill==native.BLOOD else None
            self.use(g,skill,target);self.assertEqual(g.registry.card('HERO_08').metadata.classes,(CardClass.MAGE,))
            cid=self.discover(g,rune);self.assertIn(self.entity(g,cid).id,g.state.players[1].hand)

    def test_unknown_eligible_rune_member_rolls_back_entire_skill_bonus_rng_and_consumption(self):
        g=self.game(board=(native.CARD,),mode='unknown');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.use(g,native.FROST)
        self.assertEqual(g.snapshot(),before);self.assertFalse(self.pending(g))

    def test_empty_rune_pool_finishes_skill_and_bonus_without_choice_or_rng(self):
        g=self.game(board=(native.CARD,),mode='empty');rng=g.snapshot()['rng_state']
        self.use(g,native.FROST);self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual(len(self.pending(g)),1);self.portable(g)

    def test_completed_skill_event_cannot_install_again_or_borrow_other_native_skill(self):
        g=self.game(board=(native.CARD,));self.use(g,native.FROST);self.discover(g,'frost')
        installed,event,fact=self.proof(g);spec=g.registry.player_effect(native.SPEC)
        validate_ability_origin(g.state,g.registry,g.events,spec,1,event.source_id,event,fact,installation=installed)
        with self.assertRaisesRegex(ValueError,'completed'):validate_ability_origin(g.state,g.registry,g.events,spec,1,event.source_id,event,fact)
        other=replace(event,data=(('ability_id',native.BLOOD),('ability_card_id',native.BLOOD)))
        with self.assertRaisesRegex(ValueError,'another skill'):validate_ability_origin(g.state,g.registry,g.events,spec,1,event.source_id,other,fact,installation=installed)

    def test_rehashed_installation_cannot_borrow_skill_source_owner_or_future_allocation(self):
        g=self.game(board=(native.CARD,));self.use(g,native.FROST);self.discover(g,'frost');saved=g.snapshot()
        for field,value in(('card_id',PLAIN),('controller',2),('zone','graveyard'),('next_entity_id',g.state.next_entity_id+100)):
            bad=deepcopy(saved)
            for event in bad['events']:
                if event['kind']==INSTALLED and 'ability_source_json'in event['data']:
                    fact=json.loads(event['data']['ability_source_json']);fact[field]=value
                    event['data']['ability_source_json']=json.dumps(fact,sort_keys=True,separators=(',',':'))
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
        bad=deepcopy(saved)
        for event in bad['events']:
            if event['kind']==INSTALLED and 'ability_event_json'in event['data']:
                original=json.loads(event['data']['ability_event_json']);original['sequence']+=100
                event['data']['ability_event_json']=json.dumps(original,sort_keys=True,separators=(',',':'))
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())

    def test_typed_installation_material_is_paired_finite_and_wire_required(self):
        g=self.game(board=(native.CARD,));self.use(g,native.FROST);self.discover(g,'frost');installed,event,fact=self.proof(g)
        request=AddPlayerEffect(1,native.SPEC,event.source_id,ability_event=event,ability_source=fact)
        for kwargs in({'ability_source':None},{'ability_event':None},{'capture_health_source':True},{'ability_event':replace(event,player_id=2)}):
            with self.assertRaises(ValueError):replace(request,**kwargs)
        codec=FrameCodec(g.mechanics,g.registry);encoded=codec.encode(request);self.assertEqual(codec.decode(encoded),request)
        def drop(value,key):
            if type(value)is dict:
                if 'ability_event'in value and 'ability_source'in value:del value[key];return True
                return any(drop(v,key)for v in value.values())
            if type(value)is list:return any(drop(v,key)for v in value)
            return False
        for key in('ability_event','ability_source'):
            bad=deepcopy(encoded);self.assertTrue(drop(bad,key))
            with self.assertRaises(ValueError):codec.decode(bad)
        self.assertEqual(SNAPSHOT_SCHEMA_VERSION,611);old=deepcopy(g.snapshot());old['schema_version']=610
        with self.assertRaises(SnapshotError):Game.from_snapshot(old,registry())

    def test_player_views_hide_native_event_allocation_and_private_installation_receipt(self):
        g=self.game(board=(native.CARD,));self.use(g,native.FROST)
        for player in(1,2):
            raw=json.dumps(g.for_player(player).observe())+json.dumps(g.for_player(player).legal_actions())+json.dumps(g.player_events(player))
            for key in('ability_event_json','ability_source_json','ability_source','effects_json','native_spell_bonus_installed','next_spell_bonus_effects','entered_order'):
                self.assertNotIn('"'+key+'"',raw)
        self.portable(g)

    def test_bad_final_descriptor_or_existing_dependency_never_half_registers(self):
        data=native.load_batch();bad=deepcopy(data);bad['dependencies'][-1]['record']['type']='MINION'
        with patch.object(native,'load_batch',lambda:bad):
            r=batch.registration_prefix(build_registry,'hs_sim.cards.primus_titan.register_primus_titan',lambda r:None)
            before=r.fingerprint()
            with self.assertRaises(TargetValidationError):
                with patch.object(native,'load_batch',lambda:bad):native.register_primus_titan(r)
            self.assertEqual(r.fingerprint(),before)


if __name__=='__main__':unittest.main()
