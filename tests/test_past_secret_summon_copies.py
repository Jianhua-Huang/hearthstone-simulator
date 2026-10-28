"""Actual named bodies, original attack/play facts and pre-entry copy Stealth."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import past_secret_summon_copies as native
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.copy_materials import CopyEntryMaterial
from hs_sim.engine.effects import (Buff,ChoiceOption,CopyMinion,Damage,Destroy,InvokeBehavior,
    RandomDamage,RequestChoice,ReturnToHand,Summon,Transform)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec,SummonQuantitySpec,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError

BEAR,PACK,AMBUSH,SHADOW,SNAKES,VENOM,CAT,RAT,STEED,SPIDER=native.LEAVES
P='k635.';UNIT,BIG,FILL,WATCH,DOUBLE,BC,DEAD,WEAPON=(P+x for x in ('unit','big','fill','watch','double','bc','dead','weapon'))
NOOP,AUTO,HURT,BUFF,GET,COUNTER,FAIL=(P+x for x in ('noop','auto','hurt','buff','get','counter','fail'))
NAMED={BEAR:'CS2_125',AMBUSH:'BT_707t',SNAKES:'EX1_554t',VENOM:'EX1_170',CAT:'KAR_004a',RAT:'GIL_577t',STEED:'BAR_550t',SPIDER:'REV_827t'}


def add_existing(r,bad=False):
    for item,kw in zip(native.load_batch()['existing_dependencies'],((Keyword.TAUNT,),(Keyword.POISONOUS,),())):
        raw=item['record'];cid=raw['id']
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health']+(1 if bad and cid=='GIL_577t' else 0),
            keywords=kw,metadata=replace(metadata_from_record(raw),deck_identity=cid))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();add_existing(r);native.register_past_secret_summon_copies(r)
    r.register_behavior(NOOP,lambda c:());r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,NOOP,c.source_id),))
    r.register_behavior(HURT,lambda c:(Damage(c.target_id,1,c.source_id),))
    r.register_behavior(BUFF,lambda c:(Buff(c.target_id,2,3,c.source_id),))
    r.register_behavior(GET,lambda c:(Summon(c.player_id,UNIT),))
    for cid in (NOOP,AUTO,HURT,BUFF,GET):
        extra={'targeting':TargetSpec(zones=(Zone.BOARD,Zone.HERO),kinds=(CardType.MINION,CardType.HERO))} if cid in (HURT,BUFF) else {}
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata(tribes=()),**extra))
    r.register_behavior(BC,lambda c:(Buff(c.source_id,1,3,c.source_id),));r.register_behavior(DEAD,lambda c:(Destroy(c.source_id,c.source_id),))
    for cid,attack,health in ((UNIT,3,10),(BIG,1,20),(FILL,0,10),(WATCH,0,30),(DOUBLE,0,10),(BC,3,10),(DEAD,3,10)):
        extra={'battlecry':cid} if cid in (BC,DEAD) else {}
        if cid==DOUBLE:extra['summon_quantities']=(SummonQuantitySpec(),)
        if cid==WATCH and mode!='normal':extra['triggers']=(TriggerSpec('minion_summoned' if mode=='summon' else 'secret_revealed',P+'watch'),)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=health,metadata=metadata(tribes=()),**extra))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,attack=3,durability=2,metadata=metadata(tribes=())))
    r.register_behavior(COUNTER,lambda c:(CounterSpell(c.window.id),))
    r.register_secret_condition(COUNTER,lambda c:bool(c.window and c.window.kind=='spell' and c.window.player_id!=c.player_id))
    r.register_card(CardDefinition(COUNTER,COUNTER,CardType.SPELL,keywords=(Keyword.SECRET,),
        secret=SecretSpec(COUNTER,('card_committed',),COUNTER,COUNTER),metadata=metadata(tribes=())))
    def fail(c):raise ResolutionError('K635 deliberate choice/RNG rollback')
    r.register_behavior(FAIL,fail)
    def watch(c):
        event=c.event;source=c.state.entities.get(event.source_id);target=c.state.entities.get(event.target_id)
        if mode=='summon':
            if target is None or target.controller!=c.player_id or target.card_id in (FILL,WATCH,DOUBLE):return ()
        elif source is None or source.card_id not in native.LEAVES:return ()
        options=[ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))]
        attacker=next((c.state.entities[i] for i in c.state.players[3-c.player_id].board if c.state.entities[i].card_id==UNIT),None)
        if attacker is not None:options.append(ChoiceOption('bounce','Return original attacker',(ReturnToHand(attacker.id),)))
        return (RequestChoice(c.player_id,tuple(options),c.source_id),)
    r.register_behavior(P+'watch',watch);r.validate();r.freeze();return r


@lru_cache(None)
def host():return build_cn37_local_pool_format().registry


class PastSecretSummonCopyTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand=(),*,board=(),enemy=(),other_hand=(),weapon=None,player=1,mode='normal'):
        self.mode=mode
        setups=[PlayerSetup('mage.hero',hand=hand,board=board,deck=(FILL,)*10,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('warrior.hero',hand=other_hand,board=enemy,deck=(FILL,)*10,weapon_card_id=weapon,mana=40,max_mana=40,mana_cap=40)]
        if player==2:setups.reverse()
        return Game.from_scenario(Scenario(tuple(setups),active_player=player,seed=107),registry(mode))
    def units(self,g,cid,p=1):return [g.state.entities[i] for i in g.state.players[p].board if g.state.entities[i].card_id==cid]
    def active(self,g,p=1):return [g.state.entities[i].card_id for i in g.state.players[p].secrets]
    def arm(self,g,cid,p=1):source=self.play(g,cid,player=p);g.apply(EndTurn(p));return source
    def attack(self,g,*,minion=False,p=2):
        source=self.entity(g,UNIT,p,'board').id;target=self.entity(g,UNIT,3-p,'board').id if minion else g.state.players[3-p].hero_id
        g.apply(Attack(p,source,target));return source,target
    def settle(self,g):
        while g.state.pending_choice is not None:
            g=self.portable(g);saved=g.snapshot()
            with self.assertRaisesRegex(ResolutionError,'K635'):self.choose(g,'fail')
            self.assertEqual(g.snapshot(),saved);self.choose(g)
        return g

    def test_eighteen_complete_rows_twenty_four_primary_faces_and_five_token_links(self):
        d=native.load_batch();rows={x['record']['id']:x['record'] for x in (*d['dependencies'],*d['existing_dependencies'])}
        for o in d['official_observations']:batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        self.assertEqual(len(rows),18);self.assertEqual(len(d['bilingual_parent_token_links']),5)
        self.assertEqual(d['separate_token_primary_faces_claimed'],0);self.assertFalse(d['source_scope_bound'])

    def test_all_new_tokens_keep_exact_stats_keywords_and_noncollectible_metadata(self):
        rows={x['record']['id']:x['record'] for x in native.load_batch()['dependencies']}
        for cid,kw in zip(native.TOKENS,native.TOKEN_KEYWORDS):
            d=registry().card(cid);r=rows[cid];self.assertEqual((d.cost,d.attack,d.health,d.keywords),(r['cost'],r['attack'],r['health'],kw))
            self.assertFalse(d.metadata.collectible)

    def test_ten_real_paid_hidden_secrets_and_duplicate_atomicity(self):
        for cid in native.LEAVES:
            g=self.game((cid,cid));cost=g.registry.card(cid).cost;source=self.play(g,cid)
            self.assertEqual(g.state.players[1].mana,40-cost);self.assertIn(source,g.state.players[1].secrets)
            self.assertNotIn(cid,json.dumps(g.for_player(2).observe()));saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,cid)
            self.assertEqual(g.snapshot(),saved)

    def test_bear_actual_hero_attack_then_real_taunt_blocks_later_attack(self):
        g=self.game((BEAR,),enemy=(UNIT,UNIT));self.arm(g,BEAR);attacker=g.state.players[2].board[0]
        g.apply(Attack(2,attacker,g.state.players[1].hero_id));bear=self.units(g,'CS2_125')[0]
        self.assertEqual((bear.attack,bear.health),(3,3));self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27)
        other=g.state.players[2].board[1];saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(2,other,g.state.players[1].hero_id))
        self.assertEqual(g.snapshot(),saved)

    def test_bear_accepts_hero_attacker_while_shadow_requires_minion(self):
        g=self.game((BEAR,SHADOW),weapon=WEAPON);self.play(g,BEAR);self.arm(g,SHADOW)
        g.apply(Attack(2,g.state.players[2].hero_id,g.state.players[1].hero_id))
        self.assertEqual(len(self.units(g,'CS2_125')),1);self.assertIn(SHADOW,self.active(g))

    def test_ordinary_spell_damage_is_not_a_completed_attack(self):
        g=self.game((BEAR,SHADOW),other_hand=(HURT,));self.play(g,BEAR);self.arm(g,SHADOW)
        self.play(g,HURT,g.state.players[1].hero_id,player=2);self.assertEqual(set(self.active(g)),{BEAR,SHADOW})

    def test_pack_current_copy_fixed_three_three_clears_source_injury(self):
        g=self.game((PACK,BUFF,HURT),board=(UNIT,),enemy=(UNIT,));original=self.entity(g,UNIT,1,'board').id
        self.play(g,BUFF,original);self.play(g,HURT,original);self.arm(g,PACK);self.attack(g,minion=True)
        copy=next(e for e in self.units(g,UNIT) if e.id!=original);self.assertEqual((copy.attack,copy.health,copy.max_health),(3,3,3))
        self.assertEqual(g.state.entities[original].max_health,13);self.portable(g)

    def test_pack_and_attacked_minion_secrets_ignore_hero_attack_target(self):
        for cid in (PACK,SNAKES,VENOM):
            g=self.game((cid,),enemy=(UNIT,));self.arm(g,cid);self.attack(g);self.assertIn(cid,self.active(g))

    def test_ambush_after_actual_battlecry_and_dead_minion_play_does_not_trigger(self):
        g=self.game((AMBUSH,),other_hand=(BC,));self.arm(g,AMBUSH);self.play(g,BC,player=2)
        self.assertEqual(self.entity(g,BC,2,'board').health,13);self.assertEqual(len(self.units(g,'BT_707t')),1)
        g=self.game((AMBUSH,),other_hand=(DEAD,));self.arm(g,AMBUSH);self.play(g,DEAD,player=2);self.assertIn(AMBUSH,self.active(g))

    def test_effect_summon_is_not_a_physical_minion_play(self):
        g=self.game((AMBUSH,),other_hand=(GET,));self.arm(g,AMBUSH);self.play(g,GET,player=2);self.assertIn(AMBUSH,self.active(g))

    def test_both_poisonous_summon_faces_really_kill_large_minions_in_combat(self):
        for cid in (AMBUSH,VENOM):
            g=self.game((cid,),board=(UNIT,),enemy=(BIG,) if cid==VENOM else (),other_hand=(BIG,) if cid==AMBUSH else ())
            self.arm(g,cid)
            if cid==AMBUSH:self.play(g,BIG,player=2)
            else:g.apply(Attack(2,self.entity(g,BIG,2,'board').id,self.entity(g,UNIT,1,'board').id))
            poison=self.units(g,NAMED[cid])[0].id;target=self.entity(g,BIG,2,'board').id;g.apply(EndTurn(2));g.apply(Attack(1,poison,target))
            self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)

    def test_snakes_are_three_original_named_requests_not_alternative_candidates(self):
        g=self.game((SNAKES,),board=(UNIT,),enemy=(UNIT,));self.arm(g,SNAKES);self.attack(g,minion=True)
        self.assertEqual(len(self.units(g,'EX1_554t')),3);self.assertEqual(len(g.state.card_summon_history),3)
        self.assertTrue(all(x.selected==0 for x in g.state.card_summon_history));self.portable(g)

    def test_one_remaining_slot_preserves_original_three_snake_requests(self):
        g=self.game((SNAKES,),board=(UNIT,)+(FILL,)*5,enemy=(UNIT,));self.arm(g,SNAKES);self.attack(g,minion=True)
        self.assertEqual(len(self.units(g,'EX1_554t')),1);self.assertEqual(len(g.state.card_summon_history),3)

    def test_rat_and_steed_share_real_third_hand_play_policy_not_generated_cast_count(self):
        g=self.game((RAT,STEED),other_hand=(AUTO,AUTO,NOOP));self.play(g,RAT);self.arm(g,STEED)
        self.play(g,AUTO,player=2);self.play(g,AUTO,player=2);self.assertEqual(set(self.active(g)),{RAT,STEED})
        self.play(g,NOOP,player=2);self.assertFalse(self.active(g))
        self.assertEqual((len(self.units(g,'GIL_577t')),len(self.units(g,'BAR_550t'))),(1,1))

    def test_panther_and_spider_use_successful_automatic_cast_completion(self):
        g=self.game((CAT,SPIDER),other_hand=(AUTO,));self.play(g,CAT);self.arm(g,SPIDER);self.play(g,AUTO,player=2)
        self.assertEqual((len(self.units(g,'KAR_004a')),len(self.units(g,'REV_827t'))),(1,1));self.assertFalse(self.active(g))

    def test_countered_spell_keeps_both_completed_cast_summon_secrets(self):
        g=self.game((COUNTER,CAT,SPIDER),other_hand=(NOOP,));self.play(g,COUNTER);self.play(g,CAT);self.arm(g,SPIDER)
        self.play(g,NOOP,player=2);self.assertEqual(set(self.active(g)),{CAT,SPIDER})

    def test_printed_stealth_bodies_reject_enemy_targeting_and_lose_stealth_on_attack(self):
        g=self.game((CAT,SPIDER),other_hand=(NOOP,HURT));self.play(g,CAT);self.arm(g,SPIDER);self.play(g,NOOP,player=2)
        panther=self.units(g,'KAR_004a')[0].id;spider=self.units(g,'REV_827t')[0].id;saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,HURT,panther,player=2)
        self.assertEqual(g.snapshot(),saved);g.apply(EndTurn(2))
        for target in (panther,spider):g.apply(Attack(1,target,g.state.players[2].hero_id));self.assertNotIn(Keyword.STEALTH,g.state.entities[target].keywords)

    def test_shadow_current_copy_keeps_buffs_injury_and_receives_stealth(self):
        g=self.game((SHADOW,),enemy=(UNIT,),other_hand=(BUFF,HURT));self.arm(g,SHADOW);original=self.entity(g,UNIT,2,'board').id
        self.play(g,BUFF,original,player=2);self.play(g,HURT,original,player=2);self.attack(g)
        copy=self.units(g,UNIT)[0];self.assertEqual((copy.attack,copy.health,copy.max_health),(5,12,13));self.assertIn(Keyword.STEALTH,copy.keywords);self.portable(g)

    def test_shadow_restores_stealth_even_when_original_printed_stealth_was_consumed(self):
        g=self.game((SHADOW,),enemy=('KAR_004a',));self.arm(g,SHADOW);original=self.entity(g,'KAR_004a',2,'board').id
        g.apply(Attack(2,original,g.state.players[1].hero_id))
        self.assertNotIn(Keyword.STEALTH,g.state.entities[original].keywords)
        self.assertIn(Keyword.STEALTH,self.units(g,'KAR_004a')[0].keywords);self.portable(g)

    def test_full_board_keeps_every_summoning_secret(self):
        for cid in native.LEAVES:
            g=self.game((cid,),board=(UNIT,)+(FILL,)*6,enemy=(UNIT,),other_hand=(UNIT,NOOP,NOOP,NOOP));self.arm(g,cid)
            if cid in (BEAR,SHADOW):self.attack(g)
            elif cid in (PACK,SNAKES,VENOM):self.attack(g,minion=True)
            elif cid==AMBUSH:self.play(g,UNIT,player=2)
            elif cid in (CAT,SPIDER):self.play(g,NOOP,player=2)
            else:
                for _ in range(3):self.play(g,NOOP,player=2)
            self.assertIn(cid,self.active(g));self.assertFalse(g.state.card_summon_history)

    def test_named_quantity_expansion_and_current_copy_quantities_stay_shared(self):
        g=self.game((SNAKES,),board=(DOUBLE,UNIT),enemy=(UNIT,));self.arm(g,SNAKES);self.attack(g,minion=True)
        self.assertEqual(len(self.units(g,'EX1_554t')),5);self.assertEqual(len(g.state.card_summon_history),3)
        g=self.game((SHADOW,),board=(DOUBLE,),enemy=(UNIT,));self.arm(g,SHADOW);self.attack(g)
        self.assertEqual(len(self.units(g,UNIT)),2);self.assertTrue(all(Keyword.STEALTH in e.keywords for e in self.units(g,UNIT)));self.portable(g)

    def test_reveal_waits_restore_each_original_attack_play_cast_and_hand_count_family(self):
        for cid in (BEAR,PACK,AMBUSH,CAT,RAT,SHADOW):
            g=self.game((cid,),board=(WATCH,UNIT),enemy=(UNIT,),other_hand=(UNIT,NOOP,NOOP,NOOP),mode='reveal');self.arm(g,cid)
            if cid in (BEAR,SHADOW):self.attack(g)
            elif cid==PACK:self.attack(g,minion=True)
            elif cid==AMBUSH:self.play(g,UNIT,player=2)
            elif cid==CAT:self.play(g,NOOP,player=2)
            else:
                for _ in range(3):self.play(g,NOOP,player=2)
            self.assertIsNotNone(g.state.pending_choice);g=self.settle(g);self.assertNotIn(cid,self.active(g));self.portable(g)

    def test_original_attacker_returned_during_reveal_cannot_be_copied_from_hand(self):
        g=self.game((SHADOW,),board=(WATCH,),enemy=(UNIT,),mode='reveal');self.arm(g,SHADOW);self.attack(g)
        g=self.portable(g);self.choose(g,'bounce');self.assertFalse(self.units(g,UNIT));self.assertEqual(self.entity(g,UNIT,2).zone,Zone.HAND);self.portable(g)

    def test_shadow_is_stealthed_before_summon_reactions_and_material_round_trips(self):
        g=self.game((SHADOW,),board=(WATCH,),enemy=(UNIT,),mode='summon');self.arm(g,SHADOW);original,_=self.attack(g)
        self.assertIsNotNone(g.state.pending_choice);copy=self.units(g,UNIT)[0];self.assertIn(Keyword.STEALTH,copy.keywords)
        material=next(r.request.materials[r.selected] for r in g.state.card_summon_history if r.selected is not None and isinstance(r.request.materials[r.selected],CopyEntryMaterial))
        self.assertEqual(material.minion_grant.keywords,(Keyword.STEALTH,));g=self.settle(g);self.portable(g)
        for grant in (CreatedMinionGrant(keywords=(Keyword.DIVINE_SHIELD,)),CreatedMinionGrant(attack=1,keywords=(Keyword.STEALTH,)),CreatedMinionGrant(keywords=(Keyword.STEALTH,Keyword.TAUNT))):
            with self.assertRaises(ValueError):replace(material,minion_grant=grant)
            with self.assertRaises(ValueError):CopyMinion(original,1,cause=g.state.card_summon_history[0].request.cause,minion_grant=grant)
        with self.assertRaises(ValueError):CopyMinion(original,1,minion_grant=CreatedMinionGrant(keywords=(Keyword.STEALTH,)))

    def test_three_snake_requests_resume_from_each_actual_summon_wait(self):
        g=self.game((SNAKES,),board=(WATCH,UNIT),enemy=(UNIT,),mode='summon');self.arm(g,SNAKES);self.attack(g,minion=True)
        self.assertIsNotNone(g.state.pending_choice);g=self.settle(g);self.assertEqual(len(self.units(g,'EX1_554t')),3);self.portable(g)

    def test_second_seat_shadow_uses_actual_owner_and_original_attacker(self):
        g=self.game((SHADOW,),enemy=(UNIT,),player=2);self.arm(g,SHADOW,2);self.attack(g,p=1)
        self.assertEqual(len(self.units(g,UNIT,2)),1);self.assertIn(Keyword.STEALTH,self.units(g,UNIT,2)[0].keywords)

    def test_invalid_existing_dependency_rejected_before_partial_registration(self):
        r=opening_registry();add_existing(r,bad=True);old=set(r.cards);behaviors=set(r._behaviors)
        with self.assertRaises(TargetValidationError):native.register_past_secret_summon_copies(r)
        self.assertEqual(set(r.cards),old);self.assertEqual(set(r._behaviors),behaviors)

    def test_current_schema_rejects_previous_shape_and_complete_host_reuses_original_bear(self):
        g=self.game((SHADOW,));old=json.loads(json.dumps(g.snapshot()));old['schema_version']-=1
        with self.assertRaises(SnapshotError):Game.from_snapshot(old,registry())
        r=host();g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(BEAR,),mana=20,max_mana=20,mana_cap=20),
            PlayerSetup('HERO_08',board=('TTN_480t1',),deck=('TTN_480t1',)*3))),r)
        self.play(g,BEAR);g.apply(EndTurn(1));g.apply(Attack(2,g.state.players[2].board[0],g.state.players[1].hero_id))
        self.assertEqual(len(self.units(g,'CS2_125')),1);self.assertNotIn('WON_040',r.cards)


if __name__=='__main__':unittest.main()
