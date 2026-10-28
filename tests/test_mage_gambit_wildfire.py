"""Real three-stage Mage quest progression and persistent native Wildfire."""
from dataclasses import asdict
from functools import lru_cache
import unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards import mage_gambit_wildfire as native
from hs_sim.engine import EndTurn,Game,PlayCard,PlayerSetup,ResolutionError,Scenario,UseHeroPower
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,Destroy,InvokeBehavior,
    ReplaceHero,ReplaceHeroPower,RequestChoice)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import (CardClass,CardDefinition,CardType,CastWhenDrawnSpec,DamageKind,
    Keyword,SpellSchool,TriggerSpec,Zone)
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format

GAMBIT,WILDFIRE=native.LEAVES
REWARD=native.REWARD
P='k626.'
FIRE,FROST,ARCANE,SHADOW,PLAIN,WARRIOR,NEUTRAL,DRAWCAST,UNKNOWN=(P+x for x in
    ('fire','frost','arcane','shadow','plain','warrior','neutral','drawcast','unknown'))
POWER,POWER2,HERO2,SWAP_POWER,SWAP_HERO,BOLT,AUTO,KILL,WAIT,FAIL,FULL_WATCH=(P+x for x in
    ('power','power2','hero2','swap_power','swap_hero','bolt','auto','kill','wait','fail','full_watch'))

def context(mode):return GenerationContext('k626-diagnostic-'+mode,'experimental')

@lru_cache(None)
def donor():return build_registry()

@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();old=donor();reward=old.card(REWARD)
    r.register_card(reward);r.register_behavior(reward.battlecry,old.behavior(reward.battlecry))
    r.register_player_effect(old.player_effect('m4.dawngrasp'))
    native.register_mage_gambit_wildfire(r)
    for cid,school,cls in ((FIRE,SpellSchool.FIRE,CardClass.MAGE),(FROST,SpellSchool.FROST,CardClass.MAGE),
            (ARCANE,SpellSchool.ARCANE,CardClass.MAGE),(SHADOW,SpellSchool.SHADOW,CardClass.MAGE),
            (WARRIOR,SpellSchool.FIRE,CardClass.WARRIOR),(NEUTRAL,SpellSchool.ARCANE,CardClass.NEUTRAL)):
        r.register_behavior(cid,lambda c,cid=cid:(AddToHand(c.player_id,cid,c.source_id),))
        card=CardDefinition(cid,cid,CardType.SPELL,on_play=cid,spell_school=school,metadata=metadata(cls,tribes=()))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_card(CardDefinition(PLAIN,PLAIN,CardType.MINION,attack=1,health=2,metadata=metadata(tribes=())))
    r.register_card(CardDefinition(HERO2,HERO2,CardType.HERO,health=30,metadata=metadata(CardClass.MAGE,collectible=False,tribes=())))
    r.register_behavior(P+'noop',lambda c:())
    r.register_card(CardDefinition(DRAWCAST,DRAWCAST,CardType.SPELL,spell_school=SpellSchool.FIRE,
        metadata=metadata(CardClass.MAGE,tribes=()),keywords=(Keyword.CASTS_WHEN_DRAWN,),
        cast_when_drawn=CastWhenDrawnSpec(),on_play=P+'noop'))
    for cid,value in ((POWER,1),(POWER2,2)):
        r.register_behavior(cid,lambda c,value=value:(Damage(c.state.players[3-c.player_id].hero_id,value,c.source_id,DamageKind.HERO_POWER),))
        r.register_card(CardDefinition(cid,cid,CardType.HERO_POWER,cost=2,on_use=cid,
            metadata=metadata(CardClass.MAGE,collectible=False,tribes=())))
    scripts={
        SWAP_POWER:lambda c:(ReplaceHeroPower(c.player_id,POWER2,source_id=c.source_id),),
        SWAP_HERO:lambda c:(ReplaceHero(c.player_id,HERO2,hero_power_card_id=POWER2),),
        BOLT:lambda c:(Damage(c.state.players[3-c.player_id].hero_id,1,c.source_id,DamageKind.SPELL),),
        AUTO:lambda c:(CastSpell(c.player_id,FIRE,c.source_id),),
        KILL:lambda c:(Destroy(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==REWARD),source_id=c.source_id),),
    }
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            metadata=metadata(CardClass.MAGE,tribes=())))
    members=[FIRE,FROST,ARCANE,WILDFIRE,NEUTRAL,SHADOW,WARRIOR]
    if mode=='empty':members=[SHADOW,WARRIOR]
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,1,metadata(CardClass.MAGE,tribes=()),spell_school=SpellSchool.FIRE))
        members=[SHADOW,WARRIOR,UNKNOWN]
    r.register_pool(PoolDefinition(native.POOL,'k626-full-diagnostic-'+mode,context(mode).target_id,
        context(mode).mode,tuple(PoolMember(cid)for cid in members),complete=True))
    def fail(c):raise ResolutionError('K626 deliberate continuation failure')
    r.register_behavior(FAIL,fail)
    def watch(c):
        event=c.event;source=c.state.entities.get(event.source_id);target=c.state.entities.get(event.target_id)
        relevant=(mode=='commit'and event.kind=='card_committed'and source.card_id==WILDFIRE or
            mode=='grant'and event.kind=='ability_granted'and source is not None and source.card_id==WILDFIRE or
            mode=='draw'and event.kind=='card_drawn'and source is not None and source.card_id==GAMBIT or
            mode=='reward'and event.kind=='card_added_to_hand'and target.card_id==REWARD or
            mode=='player'and event.kind=='player_effect_added'and dict(event.data)['effect_key']=='m4.dawngrasp')
        if not relevant:return ()
        change=ReplaceHero(c.player_id,HERO2,hero_power_card_id=POWER2)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('hero','Replace hero',(change,)),
            ChoiceOption('fail','Fail',(change,InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WAIT,watch)
    r.register_card(CardDefinition(WAIT,WAIT,CardType.MINION,health=20,metadata=metadata(tribes=()),
        triggers=tuple(TriggerSpec(event,WAIT)for event in('card_committed','ability_granted','card_drawn','card_added_to_hand','player_effect_added'))))
    def fill(c):
        if c.event.player_id!=c.player_id or c.state.entities[c.event.source_id].card_id!=ARCANE:return ()
        quests=(c.state.entities[i]for i in c.state.players[c.player_id].quests)
        if not any(q.card_id==GAMBIT and(q.quest_progress.stage,q.quest_progress.value)==(2,2)for q in quests):return ()
        return tuple(AddToHand(c.player_id,PLAIN,c.source_id)for _ in range(10))
    r.register_behavior(FULL_WATCH,fill)
    r.register_card(CardDefinition(FULL_WATCH,FULL_WATCH,CardType.MINION,health=20,metadata=metadata(tribes=()),
        triggers=(TriggerSpec('card_committed',FULL_WATCH),)))
    counter=P+'counter'
    r.register_behavior(counter,lambda c:(CounterSpell(dict(c.event.data)['window_id']),)if c.event.player_id!=c.player_id else ())
    r.register_card(CardDefinition(counter,counter,CardType.MINION,health=3,metadata=metadata(tribes=()),
        triggers=(TriggerSpec('card_committed',counter),)))
    r.validate();return r


class MageGambitWildfireTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand,*,mode='normal',board=(),enemy_hand=(),enemy_board=(),deck_cards=(PLAIN,ARCANE,PLAIN),hand_cap=None):
        self.mode=mode
        if mode in('commit','grant','draw','reward','player'):board=(*board,WAIT)
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=deck_cards,mana=30,max_mana=30,
            mana_cap=30,hero_power_card_id=POWER,hand_cap=hand_cap),PlayerSetup('warrior.hero',hand=enemy_hand,board=enemy_board,
                deck=(PLAIN,)*15,mana=30,max_mana=30,mana_cap=30,hero_power_card_id=POWER)),
            seed=626,generation_context=context(mode)),registry(mode))
    def quest(self,g):return self.entity(g,GAMBIT,zone='quests')
    def stage(self,g):
        q=self.quest(g).quest_progress;return(q.stage,q.value)
    def schools(self,g):
        for cid in(FIRE,FROST,ARCANE):self.play(g,cid)
    def new_quest(self,**kwargs):
        g=self.game((GAMBIT,FIRE,FROST,ARCANE),**kwargs);source=self.play(g,GAMBIT);return g,source
    def discover(self,g):
        choice=g.state.pending_choice;self.choose(g,choice.options[0].id)
    def to_final_stage(self,g):
        self.schools(g);self.schools(g)
        if g.state.pending_choice:self.discover(g)
    def complete(self,g):self.to_final_stage(g);self.schools(g)
    def hand(self,g):return tuple(g.state.entities[i].card_id for i in g.state.players[1].hand)
    def rules(self,g):return[a for a in g.state.entities[g.state.players[1].hero_id].abilities if a.kind=='health_rule'and not a.consumed]
    def hurt(self,g):return g.state.entities[g.state.players[2].hero_id].damage
    def resolve_wait(self,g,key='continue'):
        g=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,key);return g
    def power(self,g):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))

    def test_full_eight_records_ten_primary_faces_and_existing_reward_pin(self):
        d=native.load_batch();rows={x['record']['id']:x['record']for x in d['dependencies']+d['existing_dependencies']+d['evidence_only']}
        self.assertEqual(len(rows),8)
        for o in d['official_observations']:batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        self.assertEqual(asdict(registry().card(REWARD)),asdict(donor().card(REWARD)))
        self.assertEqual(asdict(registry().player_effect('m4.dawngrasp')),asdict(donor().player_effect('m4.dawngrasp')))

    def test_stage_faces_are_nonphysical_descriptors_without_generated_metadata(self):
        r=registry();stages=r.card(GAMBIT).quest.stages
        self.assertEqual(tuple(s.card_id for s in stages),(GAMBIT,)+native.DESCRIPTORS)
        self.assertEqual(tuple(s.goal for s in stages),(3,3,3))
        for cid in native.DESCRIPTORS:
            self.assertTrue(r.card(cid).choice_only);self.assertFalse(r.card(cid).hand_playable);self.assertNotIn(cid,r.pool_cards)

    def test_distinct_schools_per_stage_and_original_spell_draw(self):
        g,q=self.new_quest();self.play(g,FIRE);self.play(g,FIRE);self.assertEqual(self.stage(g),(0,1))
        self.play(g,FROST);self.play(g,ARCANE);self.assertEqual(self.stage(g),(1,0))
        rows=[r for r in g.state.draw_history if r.source_id==q]
        self.assertEqual([(r.card_id,r.outcome)for r in rows],[(ARCANE,'hand')]);self.portable(g)

    def test_before_activation_and_unqualified_school_do_not_count(self):
        g=self.game((FIRE,SHADOW,GAMBIT));self.play(g,FIRE);self.play(g,GAMBIT);self.play(g,SHADOW)
        self.assertEqual(self.stage(g),(0,0))

    def test_opponent_school_does_not_count(self):
        g,q=self.new_quest(enemy_hand=(FIRE,));g.apply(EndTurn(1));self.play(g,FIRE,player=2)
        self.assertEqual(g.state.entities[q].quest_progress.value,0)

    def test_countered_owned_school_uses_existing_attempt_policy(self):
        g,q=self.new_quest(enemy_hand=(P+'counter',));g.apply(EndTurn(1));self.play(g,P+'counter',player=2);g.apply(EndTurn(2))
        self.play(g,FIRE);self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(self.stage(g),(0,1))

    def test_automatic_cast_has_its_own_school_credit(self):
        g=self.game((GAMBIT,AUTO));self.play(g,GAMBIT);self.play(g,AUTO);self.assertEqual(self.stage(g),(0,1))

    def test_first_reward_empty_matching_deck_still_advances_stage(self):
        g,q=self.new_quest(deck_cards=(PLAIN,)*5);self.schools(g);self.assertEqual(self.stage(g),(1,0))
        self.assertFalse([r for r in g.state.draw_history if r.source_id==q])

    def test_draw_reward_automatic_cast_does_not_spill_into_next_stage(self):
        g,q=self.new_quest(deck_cards=(PLAIN,DRAWCAST,PLAIN));self.schools(g)
        self.assertEqual(self.stage(g),(1,0));self.assertEqual(len(g.state.cast_history),5)
        self.assertEqual([r.outcome for r in g.state.draw_history if r.source_id==q],['cast']);self.portable(g)

    def test_first_reward_wait_retains_completing_stage_and_original_draw(self):
        g,q=self.new_quest(mode='draw');self.schools(g)
        self.assertTrue(g.state.entities[q].quest_progress.completing);g=self.resolve_wait(g)
        self.assertEqual(self.stage(g),(1,0))

    def test_second_reward_discovery_is_full_current_class_three_school_union(self):
        g,q=self.new_quest();self.schools(g);self.schools(g)
        self.assertTrue(g.state.entities[q].quest_progress.completing);self.assertEqual(self.stage(g),(1,3))
        choice=g.state.pending_choice;self.assertEqual(len(choice.options),3)
        ids=[option.card_id for option in choice.options];self.assertEqual(len(set(ids)),3)
        for cid in ids:
            card=g.registry.card(cid);self.assertIn(card.spell_school,native.SCHOOL_SET)
            self.assertTrue(set(card.metadata.classes)&{CardClass.MAGE,CardClass.NEUTRAL})
        g=self.portable(g);self.discover(g);self.assertEqual(self.stage(g),(2,0));self.portable(g)

    def test_empty_discovery_advances_without_inventing_options(self):
        g,q=self.new_quest(mode='empty');self.to_final_stage(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.stage(g),(2,0))

    def test_unknown_eligible_discovery_rejects_and_preserves_complete_pool(self):
        g,q=self.new_quest(mode='unknown');self.schools(g);self.play(g,FIRE);self.play(g,FROST);saved=g.snapshot()
        with self.assertRaises(ResolutionError)as caught:self.play(g,ARCANE)
        self.assertIsInstance(caught.exception.__cause__,UnsupportedDefinitionError);self.assertEqual(g.snapshot(),saved)
        self.assertIn(UNKNOWN,[x.card_id for x in g.registry.pool(native.POOL,context('unknown')).members])

    def test_complete_three_stages_delivers_actual_seven_seven_and_permanent_spell_damage(self):
        g=self.game((GAMBIT,FIRE,FROST,ARCANE,BOLT));q=self.play(g,GAMBIT)
        self.complete(g);self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD)
        reward=self.entity(g,REWARD);self.assertEqual((reward.cost,reward.attack,reward.health),(5,7,7))
        self.play(g,REWARD)
        self.play(g,BOLT);self.assertEqual(self.hurt(g),4)
        self.assertEqual([g.registry.player_effect(x.spec_id).spell_damage for x in g.state.players[1].player_effects],[3])
        self.portable(g)

    def test_final_reward_full_hand_defers_until_actual_hand_space(self):
        g,q=self.new_quest(board=(FULL_WATCH,));self.complete(g)
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD);self.assertNotIn(REWARD,self.hand(g))
        self.assertEqual(g.state.quest_hand_rewards[-1].phase,'pending');g=self.portable(g)
        self.play(g,PLAIN);self.assertIn(REWARD,self.hand(g));self.assertEqual(g.state.quest_hand_rewards[-1].phase,'delivered')

    def test_final_hand_reward_wait_has_exact_original_stage_and_portable_continuation(self):
        g,q=self.new_quest(mode='reward');self.complete(g)
        self.assertTrue(g.state.entities[q].quest_progress.completing);g=self.resolve_wait(g)
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD);self.assertIn(REWARD,self.hand(g))

    def test_native_reward_player_program_wait_is_recoverable(self):
        g=self.game((REWARD,BOLT,KILL),mode='player');self.play(g,REWARD);g=self.resolve_wait(g)
        self.play(g,KILL);self.play(g,BOLT);self.assertEqual(self.hurt(g),4)

    def test_wildfire_real_payment_rule_and_separate_power_payment(self):
        g=self.game((WILDFIRE,));source=self.play(g,WILDFIRE)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[1].mana,29)
        self.assertEqual(len(self.rules(g)),1);self.power(g);self.assertEqual((self.hurt(g),g.state.players[1].mana),(2,27))
        self.portable(g)

    def test_wildfire_two_casts_install_two_independent_rules(self):
        g=self.game((WILDFIRE,WILDFIRE));self.play(g,WILDFIRE);self.play(g,WILDFIRE);self.power(g)
        self.assertEqual(self.hurt(g),3);self.assertEqual(len({a.id for a in self.rules(g)}),2)

    def test_wildfire_spell_damage_is_not_hero_power_damage(self):
        g=self.game((WILDFIRE,BOLT));self.play(g,WILDFIRE);self.play(g,BOLT);self.assertEqual(self.hurt(g),1)

    def test_wildfire_rule_survives_replacing_power_and_hero(self):
        g=self.game((WILDFIRE,SWAP_POWER,SWAP_HERO));self.play(g,WILDFIRE);self.play(g,SWAP_POWER)
        self.power(g);self.assertEqual(self.hurt(g),3)
        self.play(g,SWAP_HERO);self.assertEqual(len(self.rules(g)),1)
        g.apply(EndTurn(1));g.apply(EndTurn(2));before=self.hurt(g);self.power(g)
        self.assertEqual(self.hurt(g)-before,3);self.portable(g)

    def test_countered_wildfire_pays_without_installing_rule(self):
        g=self.game((WILDFIRE,),enemy_board=(P+'counter',));self.play(g,WILDFIRE)
        self.assertEqual(g.state.players[1].mana,29);self.assertFalse(self.rules(g))

    def test_wildfire_commit_wait_uses_current_hero_after_replacement(self):
        g=self.game((WILDFIRE,),mode='commit');original=g.state.players[1].hero_id;self.play(g,WILDFIRE)
        self.assertFalse(self.rules(g));g=self.resolve_wait(g,'hero')
        self.assertNotEqual(g.state.players[1].hero_id,original);self.assertEqual(len(self.rules(g)),1)
        self.power(g);self.assertEqual(self.hurt(g),3)

    def test_wildfire_grant_wait_preserves_one_rule_through_hero_replacement(self):
        g=self.game((WILDFIRE,),mode='grant');self.play(g,WILDFIRE);self.assertEqual(len(self.rules(g)),1)
        g=self.resolve_wait(g,'hero');self.assertEqual(len(self.rules(g)),1);self.power(g);self.assertEqual(self.hurt(g),3)

    def test_complete_local_host_executes_gambit_and_native_wildfire(self):
        f=build_cn37_local_pool_format()
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(GAMBIT,WILDFIRE),mana=10,max_mana=10,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_01')),generation_context=f.context),f.registry)
        self.play(g,GAMBIT);self.play(g,WILDFIRE);self.assertEqual(self.stage(g),(0,1))
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,g.state.players[2].hero_id))
        self.assertEqual(self.hurt(g),2)
