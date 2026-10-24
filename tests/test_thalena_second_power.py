"""Real second-slot installation through original physical power lifecycle."""
import unittest
from functools import lru_cache

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.corpse_consumer_native_cards import THALENA,KISS,register_corpse_consumer_native_cards
from hs_sim.cards.mugzee_card import MUG,ZEE,register_mugzee_card
from hs_sim.engine import (CardDefinition,CardMetadata,CardClass,CardType,Game,IllegalAction,
    PlayerSetup,Registry,ResolutionError,Scenario,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.actions import EndTurn,UseHeroPower
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddCostModifier,ChangeControl,ChoiceOption,Destroy,GainArmor,
    InvokeBehavior,ModifyCost,ReplaceHeroPower,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.hero_powers import AddHeroPower
from hs_sim.engine.model import CostSpec,PaymentType,Resource
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference

P='k506.'
HERO,PRIMARY,OTHER,UNIT,WATCH,ADD,ARM_ZEE,LOCAL,TAX,BOUNCE,QUIET,KILL,FORM,GIVE,INDIRECT,BC,REPLACE=(P+s for s in
    ('hero','primary','other','unit','watch','add','zee','local','tax','bounce','quiet','kill','form','give','indirect','bc','replace'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None)


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=Registry(P+mode);register_corpse_consumer_native_cards(r);register_mugzee_card(r)
    r.register_behavior(P+'armor',lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=1000,metadata=META))
    for cid in (PRIMARY,OTHER):
        r.register_card(CardDefinition(cid,cid,CardType.HERO_POWER,cost=2,on_use=P+'armor',metadata=META))
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,cost=1,attack=1,health=8,metadata=META))
    r.register_card(CardDefinition(BC,BC,CardType.MINION,cost=1,attack=1,health=8,battlecry=P+'armor',metadata=META))
    scripts={
        ADD:lambda c:(AddHeroPower(c.player_id,OTHER,c.source_id),),
        ARM_ZEE:lambda c:(AddHeroPower(c.player_id,ZEE,c.source_id),),
        LOCAL:lambda c:(ModifyCost(c.state.players[c.player_id].additional_hero_power_ids[0],
            CostSpec(set_to=0,card_types=(CardType.HERO_POWER,)),c.source_id),),
        TAX:lambda c:(AddCostModifier(c.player_id,CostSpec(delta=1,card_types=(CardType.HERO_POWER,)),source_id=c.source_id),),
        BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        QUIET:lambda c:(Silence(c.target_id),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        FORM:lambda c:(Transform(c.target_id,UNIT),),
        GIVE:lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        INDIRECT:lambda c:(TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]),c.source_id),),
        REPLACE:lambda c:(ReplaceHeroPower(c.player_id,OTHER,source_id=c.source_id),),
    }
    for cid,body in scripts.items():
        r.register_behavior(cid,body)
        target=TargetSpec(TargetMode.REQUIRED,kinds=(CardType.MINION,),relation='any')if cid in(BOUNCE,QUIET,KILL,FORM,GIVE,INDIRECT)else None
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=target,metadata=META))
    def fail(c):raise ResolutionError('K506 intentional second-slot continuation failure')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if mode=='before_body'and c.event.kind=='battlecry_started'and source is not None and source.card_id==THALENA:
            return (Destroy(source.id,c.source_id),)
        target=c.state.entities.get(c.event.target_id)
        if c.event.kind!='hero_power_replaced'or target is None or target.card_id!=KISS:return ()
        if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if mode in('wait','fail_choice'):
            return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),),source_id=c.source_id,
                on_select=P+'fail'if mode=='fail_choice'else None),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=8,metadata=META,
        triggers=tuple(TriggerSpec(event,P+'watch')for event in('battlecry_started','hero_power_replaced'))))
    return r


class ThalenaSecondPowerTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)
    mode='normal'

    def game(self,hand=(THALENA,THALENA),player=1,mode='normal',own=(UNIT,),enemy=(),
            enemy_hand=(),primary=PRIMARY,start=None,corpses=20):
        self.mode=mode
        if mode in('before_body','wait','fail','fail_choice'):own=(*own,WATCH)
        players=tuple(PlayerSetup(HERO,hero_power_card_id=primary if p==player else PRIMARY,
            hand=hand if p==player else enemy_hand,board=own if p==player else enemy,
            deck=(UNIT,)*8,mana=30,max_mana=30,mana_cap=30,corpses=corpses)for p in(1,2))
        return Game.from_scenario(Scenario(players,active_player=start or player,seed=506),fixture(mode))

    def second(self,g,player=1):return g.state.entities[g.state.players[player].additional_hero_power_ids[0]]

    def use(self,g,power,target=None,player=1):g.apply(UseHeroPower(player,power,target))

    def test_both_seats_second_battlecry_replaces_only_secondary_and_pays_both_roots(self):
        for player in(1,2):
            with self.subTest(player=player):
                g=self.game(player=player);primary=g.state.players[player].hero_power_id
                self.play(g,THALENA,player=player);old=self.second(g,player).id
                self.play(g,THALENA,player=player);new=self.second(g,player)
                self.assertNotEqual(old,new.id);self.assertEqual(new.card_id,KISS)
                self.assertEqual(g.state.players[player].hero_power_ids,(primary,new.id))
                self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
                self.assertEqual(g.state.players[player].mana,22)
                self.assertEqual(g.state.players[player].resources[Resource.CORPSES],20)

    def test_different_existing_secondary_is_retired_in_same_role(self):
        g=self.game(hand=(ADD,THALENA));primary=g.state.players[1].hero_power_id
        self.play(g,ADD);old=self.second(g).id;self.play(g,THALENA)
        self.assertEqual(g.state.players[1].hero_power_ids,(primary,self.second(g).id))
        self.assertEqual((g.state.entities[old].card_id,g.state.entities[old].zone),(OTHER,Zone.GRAVEYARD))
        self.assertEqual(self.second(g).card_id,KISS)

    def test_same_card_reinstallation_follows_existing_fresh_entity_usage_contract(self):
        g=self.game();self.play(g,THALENA);old=self.second(g).id;primary=g.state.players[1].hero_power_id
        target=self.entity(g,UNIT,zone='board').id
        self.use(g,primary);self.use(g,old,target)
        self.assertEqual((g.state.players[1].hero_power_uses_this_turn,g.state.entities[old].uses_this_turn),(2,1))
        self.play(g,THALENA);new=self.second(g)
        self.assertEqual((new.uses_this_turn,g.state.entities[primary].uses_this_turn),(0,1))
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn,2)
        with self.assertRaises(IllegalAction):self.use(g,primary)
        self.use(g,new.id,target)
        self.assertEqual((g.state.players[1].hero_power_uses_this_turn,g.state.players[1].resources[Resource.CORPSES]),(3,14))

    def test_retired_power_id_cannot_activate_new_same_card(self):
        g=self.game();self.play(g,THALENA);old=self.second(g).id;self.play(g,THALENA);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.use(g,old,self.entity(g,UNIT,zone='board').id)
        self.assertEqual(g.snapshot(),saved)

    def test_old_local_cost_and_uses_do_not_migrate_to_new_printed_power(self):
        g=self.game(hand=(THALENA,LOCAL,THALENA));self.play(g,THALENA);old=self.second(g).id
        self.play(g,LOCAL);self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[old]).amount,0)
        self.use(g,old,self.entity(g,UNIT,zone='board').id);self.play(g,THALENA)
        quote=quote_cost(g.state,g.registry,self.second(g))
        self.assertEqual((quote.amount,quote.payment,self.second(g).uses_this_turn),(3,PaymentType.CORPSES,0))

    def test_shared_power_cost_modifier_applies_to_new_secondary_and_original_primary(self):
        g=self.game(hand=(THALENA,TAX,THALENA));self.play(g,THALENA);self.play(g,TAX);self.play(g,THALENA)
        player=g.state.players[1];new=self.second(g)
        self.assertEqual((quote_cost(g.state,g.registry,new).amount,
            quote_cost(g.state,g.registry,g.state.entities[player.hero_power_id]).amount),(4,3))
        self.use(g,new.id,self.entity(g,UNIT,zone='board').id)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],16)

    def test_original_primary_replacement_preserves_installed_kiss_identity_and_use(self):
        g=self.game(hand=(THALENA,REPLACE));self.play(g,THALENA);second=self.second(g).id
        self.use(g,second,self.entity(g,UNIT,zone='board').id);self.play(g,REPLACE)
        self.assertEqual(self.second(g).id,second);self.assertEqual(self.second(g).uses_this_turn,1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,OTHER)

    def test_source_death_return_silence_transform_or_control_keeps_new_power(self):
        for command in(KILL,BOUNCE,QUIET,FORM,GIVE):
            with self.subTest(command=command):
                g=self.game(hand=(THALENA,THALENA,command));self.play(g,THALENA);source=self.play(g,THALENA)
                installed=self.second(g).id;self.play(g,command,source)
                self.assertEqual(self.second(g).id,installed)
                before=g.state.players[1].resources[Resource.CORPSES]
                self.use(g,installed,self.entity(g,UNIT,zone='board').id)
                self.assertEqual(g.state.players[1].resources[Resource.CORPSES],before-3)

    def test_source_dies_before_body_and_original_accepted_battlecry_still_replaces(self):
        g=self.game(hand=(ADD,THALENA),mode='before_body');self.play(g,ADD);old=self.second(g).id
        source=self.play(g,THALENA);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual((self.second(g).card_id,g.state.entities[old].zone),(KISS,Zone.GRAVEYARD))

    def test_indirect_opponents_battlecry_replaces_its_own_secondary(self):
        g=self.game(hand=(INDIRECT,),enemy=(THALENA,),enemy_hand=(ADD,),start=2)
        self.play(g,ADD,player=2);old=self.second(g,2).id;primary=g.state.players[2].hero_power_id
        g.apply(EndTurn(2));self.play(g,INDIRECT,self.entity(g,THALENA,2,'board').id)
        self.assertEqual(g.state.players[2].hero_power_ids,(primary,self.second(g,2).id))
        self.assertEqual((self.second(g,2).card_id,g.state.entities[old].zone),(KISS,Zone.GRAVEYARD))
        self.assertFalse(g.state.players[1].additional_hero_power_ids)

    def test_real_zee_accepted_double_survives_its_replacement_without_future_repeat_source(self):
        g=self.game(hand=(ARM_ZEE,UNIT,UNIT,UNIT,UNIT,THALENA,BC),own=(),primary=MUG)
        self.play(g,ARM_ZEE);old=self.second(g).id
        for _ in range(4):self.play(g,UNIT)
        before=g.state.players[1].mana;self.play(g,THALENA)
        self.assertEqual(g.state.players[1].mana,before-4)
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        replacements=[e for e in g.events if e.kind=='hero_power_replaced']
        self.assertEqual(len(replacements),2)
        self.assertEqual(self.second(g).card_id,KISS)
        before=g.state.entities[g.state.players[1].hero_id].armor;self.play(g,BC)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,before+1)

    def test_replacement_notification_sees_complete_new_slot_and_restores_once(self):
        g=self.game(mode='wait');self.play(g,THALENA);old=self.second(g).id;self.play(g,THALENA)
        self.assertIsNotNone(g.state.pending_choice);new=self.second(g).id
        self.assertNotEqual(old,new);self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].mana,22);self.portable(g)
        self.choose(g);self.assertEqual(self.second(g).id,new);self.assertEqual(g.state.players[1].mana,22)

    def test_failed_replacement_notification_rolls_back_payment_retirement_and_primary(self):
        g=self.game(mode='fail');self.play(g,THALENA);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,THALENA)
        self.assertEqual(g.snapshot(),saved)

    def test_failed_choice_preserves_original_paid_wait_and_new_identity(self):
        g=self.game(mode='fail_choice');self.play(g,THALENA);self.play(g,THALENA);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_next_owner_turn_refreshes_new_power_and_keeps_original_aggregate_history(self):
        g=self.game();self.play(g,THALENA);self.play(g,THALENA);new=self.second(g).id
        target=self.entity(g,UNIT,zone='board').id;self.use(g,new,target)
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual((self.second(g).id,self.second(g).uses_this_turn),(new,0))
        self.use(g,new,target);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],14)

    def test_unreviewed_multiple_extra_slots_remain_explicit_and_transactional(self):
        g=self.game(hand=(ADD,ADD,THALENA));self.play(g,ADD);self.play(g,ADD);saved=g.snapshot()
        with self.assertRaises(ResolutionError)as caught:self.play(g,THALENA)
        self.assertIsInstance(caught.exception.__cause__,UnsupportedDefinitionError)
        self.assertEqual(g.snapshot(),saved)
