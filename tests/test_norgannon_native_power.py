"""Actual native power, copied completion state, future taxes and real secrets."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json,unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import norgannon_native_power as native
from hs_sim.engine import (CardClass,CardDefinition,CardType,EndTurn,Game,Keyword,PlayerSetup,
    ResolutionError,Scenario,SnapshotError,UseMinionAbility)
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Destroy,GrantSpellDamage,InvokeBehavior,
    RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.minion_ability_power import (DoubleRemainingMinionAbilities,MinionAbilityPowerProfile,
    PREFIX as MARKER_PREFIX,marker,validate_carrier,value)
from hs_sim.engine.information import VIEW_VERSION
from hs_sim.engine.model import CardMetadata,Enchantment,Rarity,SecretSpec,TargetSpec,TriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.secrets import area_count
from hs_sim.engine.serialization import canonical_hash
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P='k615.'
UNIT,NOOP,ALT,LOC,COPY,BASE,BOUNCE,KILL,MUTE,POWER,USEDWAIT,FAIL=(P+x for x in(
    'unit','noop','weapon','location','copy','base','bounce','kill','mute','spellpower','wait','fail'))
SECRETS=tuple(P+'secret'+str(i)for i in range(6));UNKNOWN=P+'unknown'
META=CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


def context():return GenerationContext(P+'complete','experimental')


@lru_cache(None)
def registry(mode='normal',role='writer'):
    if mode=='power_wait':
        r=batch.registration_prefix(build_registry,'hs_sim.cards.norgannon_native_power.register_norgannon_native_power',lambda r:None)
        register=r.register_behavior
        def intercept(name,fn):
            if name==native.PREFIX+'after':
                original=fn
                def fn(c):
                    work=tuple(original(c))
                    return ()if not work else(RequestChoice(c.player_id,(
                        ChoiceOption('continue','Apply original doubling',work),
                        ChoiceOption('fail','Fail',(InvokeBehavior(FAIL,c.source_id,c.player_id),))),c.source_id),)
            register(name,fn)
        with patch.object(r,'register_behavior',side_effect=intercept):native.register_norgannon_native_power(r)
    else:r=build_registry()
    r.register_behavior(NOOP,lambda c:())
    def fail(c):raise ResolutionError('K615 deliberate original continuation failure')
    r.register_behavior(FAIL,fail)
    for cid,body in(
        (COPY,lambda c:(CopyMinion(c.target_id,c.player_id),)),
        (BASE,lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),)),
        (BOUNCE,lambda c:(ReturnToHand(c.target_id),)),
        (KILL,lambda c:(Destroy(c.target_id,c.source_id),)),
        (MUTE,lambda c:(Silence(c.target_id),)),
        (POWER,lambda c:(GrantSpellDamage(c.target_id,4,c.source_id),))):
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,targeting=TargetSpec()))
    def used_wait(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id!=native.NORGANNON:return ()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('copy','Copy before doubling',(CopyMinion(c.event.source_id,c.player_id),)),
            ChoiceOption('silence','Silence before doubling',(Silence(c.event.source_id),))),c.source_id),)
    r.register_behavior(USEDWAIT,used_wait)
    r.register_card(CardDefinition(USEDWAIT,USEDWAIT,CardType.MINION,health=8,triggers=(TriggerSpec('minion_ability_used',USEDWAIT),)))
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,cost=3,attack=0,health=80))
    r.register_card(CardDefinition(NOOP,NOOP,CardType.SPELL,cost=1,on_play=NOOP))
    r.register_card(CardDefinition(ALT,ALT,CardType.WEAPON,cost=2,attack=2,durability=3))
    r.register_card(CardDefinition(LOC,LOC,CardType.LOCATION,cost=2,durability=2,on_use=NOOP))
    r.register_card(CardDefinition(P+'hero_power',P+'hero_power',CardType.HERO_POWER,cost=2,on_use=NOOP))
    def steal(c):
        sources=[i for i in c.state.players[3-c.player_id].board if c.state.entities[i].card_id==native.NORGANNON]
        return(ChangeControl(sources[0],c.player_id),)if sources else()
    r.register_behavior(P+'steal',steal)
    r.register_card(CardDefinition(P+'steal',P+'steal',CardType.MINION,health=1,deathrattle=P+'steal'))
    r.register_secret_condition(P+'never',lambda c:False)
    for cid in SECRETS:
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=3,metadata=META,keywords=(Keyword.SECRET,),
            secret=SecretSpec(cid,('card_played',),P+'never',NOOP)))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    members=SECRETS
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,3,META,keywords=(Keyword.SECRET,)))
        members=(UNKNOWN,)
    r.register_pool(PoolDefinition(native.POOL,P+'secrets-v1',context().target_id,'experimental',tuple(PoolMember(cid)for cid in members),complete=True))
    r.validate();return r


class NorgannonNativePowerTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'

    def game(self,hand=(),*,board=(),enemy_hand=(),enemy_board=(UNIT,),mode='normal',player=1,hero='HERO_08',hero_power=None):
        self.mode=mode
        setups=tuple(PlayerSetup(hero if p==player else'HERO_08',hand=hand if p==player else enemy_hand,
            board=board if p==player else enemy_board,deck=(NOOP,)*25,mana=30,max_mana=30,mana_cap=30,
            hero_power_card_id=hero_power)for p in(1,2))
        return Game.from_scenario(Scenario(setups,active_player=player,seed=615,generation_context=context()),registry(mode))

    def source(self,g,p=1):return self.entity(g,native.NORGANNON,p,'board')

    def use(self,g,skill,target=None,*,source=None,player=1):
        source=self.source(g,player).id if source is None else source
        before=g.state.players[player].mana;g.apply(UseMinionAbility(player,source,skill,target))
        self.assertEqual(g.state.players[player].mana,before);return source

    def next_turn(self,g,p=1):g.apply(EndTurn(p));g.apply(EndTurn(3-p))

    def power(self,g,skill,source=None):
        return value(g.registry,g.state.entities[self.source(g).id if source is None else source],skill)

    def test_nine_original_rows_eight_faces_five_evidence_rows_and_base_five_one_one(self):
        d=native.load_batch();rows={r['record']['id']:r for key in('cards','dependencies','evidence_only')for r in d[key]}
        self.assertEqual((len(rows),len(d['official_observations'])),(9,8))
        for o in d['official_observations']:
            batch.check_face(rows[o['card_id']]['record'],o['face'],o['locale'],
                display_normalizations=d['display_normalizations'].get(o['card_id']),numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        self.assertEqual(tuple(map(tuple,d['printed_base_values'])),native.BASE_VALUES)
        for cid in native.SKILLS:self.assertTrue(registry().card(cid).choice_only);self.assertNotIn(cid,registry().pool_cards)
        for cid in native.EVIDENCE:self.assertNotIn(cid,registry().cards)
        self.assertFalse(d['new_token_ids']);self.assertEqual(native.COLLECTIBLE_ROOTS,())

    def test_both_seats_pay_six_and_start_with_original_unconsumed_values(self):
        for player in(1,2):
            g=self.game((native.NORGANNON,),player=player);sid=self.play(g,native.NORGANNON,player=player)
            self.assertEqual(g.state.players[player].mana,24)
            self.assertEqual([value(g.registry,g.state.entities[sid],s)for s in native.SKILLS],[5,1,1])
            self.assertFalse(any(a.consumed for a in g.state.entities[sid].abilities if a.kind=='activated'))
            self.assertFalse(g.state.cast_history)

    def test_damage_is_five_ten_or_twenty_from_completed_native_skills(self):
        for prior,expected in((0,5),(1,10),(2,20)):
            g=self.game((POWER,),board=(native.NORGANNON,));sid=self.source(g).id
            self.play(g,POWER,sid)
            for skill in native.SKILLS[1:1+prior]:self.use(g,skill);self.next_turn(g)
            target=self.entity(g,UNIT,2,'board').id;hp=g.state.entities[target].health
            self.use(g,native.SKILLS[0],target)
            self.assertEqual(g.state.entities[target].health,hp-expected)
            self.assertFalse([r for r in g.state.cast_history if r.card_id in native.SKILLS])
            self.assertLessEqual(sum(marker(e)is not None for e in g.state.entities[sid].enchantments),2)

    def test_tax_waits_for_original_opponent_next_turn_applies_all_card_types_then_expires(self):
        g=self.game((KILL,),board=(native.NORGANNON,),enemy_hand=(UNIT,UNIT,NOOP,ALT,LOC))
        sid=self.use(g,native.SKILLS[1]);self.assertFalse(g.state.players[2].cost_modifiers)
        self.assertEqual(area_count(g.state.players[2],g.registry),0);self.play(g,KILL,sid)
        self.portable(g);g.apply(EndTurn(1))
        self.assertFalse(g.state.players[2].player_effects);self.assertEqual(g.state.players[2].cost_modifiers[0].spec.delta,1)
        for cid,cost in((UNIT,4),(NOOP,2),(ALT,3),(LOC,3)):
            eid=self.entity(g,cid,2).id;self.assertEqual(g.quote_cost(eid).amount,cost)
            mana=g.state.players[2].mana;self.play(g,cid,player=2);self.assertEqual(g.state.players[2].mana,mana-cost)
        self.portable(g);g.apply(EndTurn(2));self.assertFalse(g.state.players[2].cost_modifiers)
        g.apply(EndTurn(1));self.assertEqual(g.quote_cost(self.entity(g,UNIT,2).id).amount,3)

    def test_tax_can_scale_to_four_without_increasing_hero_power_cost(self):
        g=self.game(board=(native.NORGANNON,),enemy_hand=(UNIT,),hero_power=P+'hero_power')
        self.use(g,native.SKILLS[0],self.entity(g,UNIT,2,'board').id);self.next_turn(g)
        self.use(g,native.SKILLS[2]);self.next_turn(g);self.use(g,native.SKILLS[1]);g.apply(EndTurn(1))
        self.assertEqual(g.quote_cost(self.entity(g,UNIT,2).id).amount,7)
        power=g.state.players[2].hero_power_ids[0];self.assertEqual(g.quote_cost(power).amount,2)

    def test_damage_deathrattle_control_change_keeps_original_actor_and_boosts_current_carrier(self):
        g=self.game(board=(native.NORGANNON,),enemy_board=(P+'steal',));sid=self.source(g).id
        self.use(g,native.SKILLS[0],self.entity(g,P+'steal',2,'board').id)
        self.assertEqual(g.state.entities[sid].controller,2);self.assertIn(sid,g.state.players[2].board)
        self.assertEqual(self.power(g,native.SKILLS[1],sid),2)
        used=next(e for e in g.events if e.kind=='minion_ability_used')
        boosted=next(e for e in g.events if e.kind=='minion_ability_power_doubled')
        self.assertEqual((used.player_id,boosted.player_id),(1,2));self.portable(g)

    def test_secret_batch_scales_one_two_four_as_real_casts_even_for_warrior(self):
        for prior,expected in((0,1),(1,2),(2,4)):
            g=self.game(board=(native.NORGANNON,),hero='HERO_01')
            for skill in native.SKILLS[:prior]:
                self.use(g,skill,self.entity(g,UNIT,2,'board').id if skill==native.SKILLS[0]else None);self.next_turn(g)
            before=len(g.state.cast_history);self.use(g,native.SKILLS[2])
            casts=g.state.cast_history[before:];self.assertEqual(len(casts),expected)
            self.assertTrue(all(c.card_id in SECRETS for c in casts));self.assertLessEqual(len(g.state.players[1].secrets),5)

    def test_opponent_counterspell_does_not_counter_native_secret_ability(self):
        g=self.game(('CORE_EX1_287',),enemy_board=(native.NORGANNON,),player=2)
        self.play(g,'CORE_EX1_287',player=2);g.apply(EndTurn(2));before=len(g.state.cast_history)
        self.use(g,native.SKILLS[2]);self.assertEqual(len(g.state.cast_history),before+1)
        self.assertEqual(len(g.state.players[2].secrets),1);self.assertEqual(len(g.state.players[1].secrets),1)

    def test_current_copy_retains_boost_and_spent_skill_while_base_copy_restarts(self):
        g=self.game((COPY,BASE),board=(native.NORGANNON,));original=self.use(g,native.SKILLS[1])
        self.play(g,COPY,original);current=g.state.players[1].board[-1]
        self.assertEqual(self.power(g,native.SKILLS[0],current),10)
        self.assertTrue(next(a for a in g.state.entities[current].abilities if a.kind=='activated'and a.activation.id==native.SKILLS[1]).consumed)
        self.play(g,BASE,original);base=g.state.players[1].board[-1]
        self.assertEqual(self.power(g,native.SKILLS[0],base),5)
        self.assertFalse(any(a.consumed for a in g.state.entities[base].abilities if a.kind=='activated'));self.portable(g)

    def test_copy_before_original_completion_boost_does_not_invent_the_missing_marker(self):
        g=self.game((native.NORGANNON,),board=(USEDWAIT,));original=self.play(g,native.NORGANNON)
        self.use(g,native.SKILLS[1]);self.assertEqual(self.power(g,native.SKILLS[0],original),5)
        self.portable(g);self.choose(g,'copy');copy=g.state.players[1].board[-1]
        self.assertNotEqual(copy,original);self.assertEqual(self.power(g,native.SKILLS[0],original),10)
        self.assertEqual(self.power(g,native.SKILLS[0],copy),5);self.portable(g)

    def test_bounce_replay_resets_markers_and_used_skills_but_original_tax_persists(self):
        g=self.game((BOUNCE,),board=(native.NORGANNON,));sid=self.use(g,native.SKILLS[1]);self.play(g,BOUNCE,sid)
        self.play(g,native.NORGANNON);self.assertEqual(self.power(g,native.SKILLS[0]),5)
        self.assertFalse(any(a.consumed for a in self.source(g).abilities if a.kind=='activated'))
        g.apply(EndTurn(1));self.assertEqual(g.state.players[2].cost_modifiers[0].spec.delta,1)

    def test_silence_before_captured_upgrade_leaves_no_ability_or_marker(self):
        g=self.game((native.NORGANNON,),board=(USEDWAIT,));sid=self.play(g,native.NORGANNON)
        self.use(g,native.SKILLS[1]);self.choose(g,'silence')
        self.assertFalse([a for a in g.state.entities[sid].abilities if a.kind=='activated'])
        self.assertFalse([e for e in g.state.entities[sid].enchantments if marker(e)is not None]);self.portable(g)

    def test_new_power_effect_waits_serializes_restores_and_failed_resume_is_atomic(self):
        g=self.game(board=(native.NORGANNON,),mode='power_wait');self.use(g,native.SKILLS[1])
        before=g.snapshot();self.assertEqual(self.power(g,native.SKILLS[0]),5);restored=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.power(g,native.SKILLS[0]),10);self.portable(g)

    def test_unknown_eligible_secret_rolls_back_usage_marker_rng_and_allocation(self):
        g=self.game(board=(native.NORGANNON,),mode='unknown');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.use(g,native.SKILLS[2])
        self.assertEqual(g.snapshot(),before)

    def test_marker_shape_cannot_mix_numeric_fields_lifetimes_or_fake_identities(self):
        g=self.game(board=(native.NORGANNON,));sid=self.use(g,native.SKILLS[1])
        original=next(e for e in g.state.entities[sid].enchantments if marker(e)is not None)
        for change in(dict(attack=1),dict(expires_turn=1),dict(remove_on_silence=False),dict(source_id=None),dict(label=MARKER_PREFIX+'bad')):
            with self.assertRaises(ValueError):replace(original,**change)
        for replacement in(replace(original,label=MARKER_PREFIX+'unknown:'+native.SKILLS[1]),
                replace(original,label=MARKER_PREFIX+native.PROFILE+':unknown')):
            with self.assertRaises(ValueError):validate_carrier(g.registry,native.NORGANNON,CardType.MINION,(replacement,))
        with self.assertRaises(ValueError):validate_carrier(g.registry,UNIT,CardType.MINION,(original,))
        with self.assertRaises(ValueError):validate_carrier(g.registry,native.NORGANNON,CardType.MINION,(original,replace(original,id=original.id+1)))

    def test_rehashed_snapshot_rejects_unconsumed_skill_marker_and_duplicate_marker(self):
        g=self.game(board=(native.NORGANNON,));sid=self.use(g,native.SKILLS[1]);saved=g.snapshot()
        for mode in('unconsumed','duplicate'):
            bad=deepcopy(saved);entities=bad['state']['entities']
            entity=next(e for e in entities.values()if e['id']==sid)if isinstance(entities,dict)else next(e for e in entities if e['id']==sid)
            marked=next(e for e in entity['enchantments']if e['label'].startswith(MARKER_PREFIX))
            if mode=='unconsumed':marked['label']=MARKER_PREFIX+native.PROFILE+':'+native.SKILLS[0]
            else:
                duplicate=deepcopy(marked);duplicate['id']=bad['state']['next_attachment_id'];bad['state']['next_attachment_id']+=1
                entity['enchantments'].append(duplicate)
            bad['state_hash']=canonical_hash({k:v for k,v in bad.items()if k not in('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())

    def test_public_remaining_power_is_visible_to_both_seats_without_marker_or_source_ids(self):
        g=self.game(board=(native.NORGANNON,));self.use(g,native.SKILLS[1])
        for player in(1,2):
            observation=g.for_player(player).observe()['observation'];self.assertEqual(observation['version'],VIEW_VERSION)
            abilities=observation['players'][0]['board'][0]['minion_abilities']
            self.assertEqual({a['ability_id']:a.get('power')for a in abilities},{native.SKILLS[0]:10,native.SKILLS[1]:None,native.SKILLS[2]:2})
            raw=json.dumps(observation)+json.dumps(g.player_events(player))
            for private in(MARKER_PREFIX,'attachment_id','resolution_frame','rng_state','zone_epoch'):self.assertNotIn(private,raw)

    def test_registered_profile_rejects_invalid_values_wrong_source_and_duplicate_registration(self):
        r=registry(role='profile-only');profile=r.minion_ability_power_profiles[native.PROFILE]
        for invalid in(replace(profile,base_values=((native.SKILLS[0],-1),*profile.base_values[1:])),
                replace(profile,card_id=UNIT),replace(profile,base_values=profile.base_values[:-1])):
            with self.assertRaises(ValueError):r.register_minion_ability_power_profile(invalid)
        with self.assertRaises(ValueError):r.register_minion_ability_power_profile(profile)

    def test_complete_local_host_has_six_defined_secrets_and_all_native_skill_entries(self):
        fmt=build_cn37_local_pool_format();pool=resolve_candidates(fmt.registry,fmt.context,native.POOL,native.SECRET_QUERY,
            current_class=CardClass.WARRIOR,source_card_id=native.NORGANNON,player_id=1)
        self.assertEqual(len(pool),6);self.assertTrue(all(x.card_id in fmt.registry.cards for x in pool))
        for skill in native.SKILLS:
            g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(native.NORGANNON,),deck=('CORE_EX1_028',)*5,mana=10,max_mana=10),
                PlayerSetup('HERO_08')),generation_context=fmt.context,seed=615),fmt.registry)
            sid=self.play(g,native.NORGANNON)
            g.apply(UseMinionAbility(1,sid,skill,g.state.players[2].hero_id if skill==native.SKILLS[0]else None))
            self.assertEqual(Game.from_snapshot(g.snapshot(),fmt.registry).snapshot(),g.snapshot())

    def test_invalid_last_descriptor_cannot_half_register_native_profile_or_faces(self):
        r=batch.registration_prefix(build_registry,'hs_sim.cards.norgannon_native_power.register_norgannon_native_power',lambda r:None)
        data=deepcopy(native.load_batch());data['dependencies'][-1]['record']['type']='MINION';before=r.fingerprint()
        with patch.object(native,'load_batch',lambda:data),self.assertRaises(TargetValidationError):native.register_norgannon_native_power(r)
        self.assertEqual(r.fingerprint(),before)


if __name__=='__main__':unittest.main()
