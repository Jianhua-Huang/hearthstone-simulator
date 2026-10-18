"""Native quest and weapon execute actual original options through shared bodies."""
from dataclasses import replace
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import unittest

from hs_sim.cards.native_origin_stone_cards import CARD, REWARD, register_native_origin_stone_cards
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, ChooseBranch,
    ChooseOneSpec, EndTurn, Game, Keyword, PlayCard, PlayerSetup, Rarity, Registry, Scenario,
    SelectChoice, SnapshotError)
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, EquipWeapon, GainArmor, InvokeBehavior,
    ModifyWeapon, RequestChoice, TransferWeapon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import ChoicePurpose, CostSpec, EquippedWeaponReference, LimitedTriggerSpec, Zone
from hs_sim.engine.pools import (DiscoverFromPool, DiscoveryGiftPool, GenerationContext,
    PoolCard, PoolDefinition, PoolMember, PoolQuery)
from hs_sim.engine.dark_gifts import DARK_GIFTS, GrantDarkGift
from hs_sim.engine.hand_choice_followups import DiscoverForPlayFollowup
from hs_sim.engine.stored_gift_discovery import DiscoverDeckDarkGift
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.choose_branch_state import SetChooseBranch
from hs_sim.engine.costs import local_cost
from hs_sim.engine.discovery_offers import offer_for_result
from hs_sim.engine.offered_card_selection import OfferedCardSelection
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.generated_activation_receipts import RETAINED_PROFILE
from hs_sim.engine.zones import CardReference, ChooseFromZone, ModifyStoredCost

P = 'origin-stone-test.'
HERO, POWER, POWER2, SKIP, MIN, SPELL, WEAPON, LOCATION, HERO_CARD = (
    P + v for v in ('hero','power','power2','skip','minion','spell','weapon','location','hero-card'))
DISC, PREP, NESTED, HISTORY, CHOOSE_SPELL, CHOOSE_MIN = (
    P + v for v in ('discover','prepare','nested','history','choose-spell','choose-min'))
LOWER, KILL = P+'lower-weapon', P+'kill-board'
POOL, INNER = P + 'pool', P + 'inner'
CONTEXT = GenerationContext('k177-native-origin-stone', 'experimental')
PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
KINDS = dict(minion=MIN, spell=SPELL, weapon=WEAPON, location=LOCATION, hero=HERO_CARD,
    nested=NESTED, history=HISTORY, choose_spell=CHOOSE_SPELL, choose_minion=CHOOSE_MIN)
META = CardMetadata(True, (CardClass.MAGE,), Rarity.COMMON, tribes=())


@lru_cache(maxsize=None)
def registry(kind='minion', mode='plain', role='writer', pin=PIN):
    if role not in ('writer','reader') or pin != PIN: raise ValueError('Immutable independent fixture identity required')
    r = Registry('native-origin-stone-' + kind + '-' + mode)
    register_native_origin_stone_cards(r)
    r.register_behavior(P+'noop', lambda c: ())
    r.register_behavior(P+'minion', lambda c: (GainArmor(c.player_id, c.source.attack),))
    r.register_behavior(P+'weapon', lambda c: (GainArmor(c.player_id, 2),))
    r.register_behavior(P+'location', lambda c: (GainArmor(c.player_id, 3),))
    r.register_behavior(P+'hero', lambda c: (GainArmor(c.player_id, 4),))
    def fail(c): raise ResolutionError('Original offered body failure')
    r.register_behavior(P+'fail', fail)
    r.register_behavior(P+'spell', fail if mode == 'fail_body' else
        lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 2, c.source_id),))
    for cid in (POWER, POWER2): r.register_card(CardDefinition(cid, cid, CardType.HERO_POWER, on_use=P+'noop'))
    for cid, ctype, kw in (
        (SKIP,CardType.MINION,dict(attack=1,health=2)),
        (MIN,CardType.MINION,dict(attack=3,health=4,battlecry=P+'minion')),
        (SPELL,CardType.SPELL,dict(on_play=P+'spell')),
        (WEAPON,CardType.WEAPON,dict(attack=2,durability=3,battlecry=P+'weapon')),
        (LOCATION,CardType.LOCATION,dict(durability=2,on_use=P+'location')),
        (HERO_CARD,CardType.HERO,dict(health=30,hero_card=True,hero_armor=5,initial_hero_power=POWER2,on_play=P+'hero'))):
        if mode=='gift_living_dormant'and cid in(SKIP,MIN):kw=dict(kw,dormant_turns=2,battlecry=None)
        definition=CardDefinition(cid,cid,ctype,cost=4,metadata=META,**kw)
        r.register_card(definition);r.register_pool_card(PoolCard.from_definition(definition))
    for branch, amount in (('left',11),('right',22),('both',33)):
        r.register_behavior(P+branch,lambda c,n=amount:(GainArmor(c.player_id,n),))
    choice=ChooseOneSpec((ChooseBranch('left','Left',P+'left'),ChooseBranch('right','Right',P+'right')),
        ChooseBranch('both','Both',P+'both'))
    for cid,ctype in ((CHOOSE_SPELL,CardType.SPELL),(CHOOSE_MIN,CardType.MINION)):
        definition=CardDefinition(cid,cid,ctype,cost=4,choose_one=choice,metadata=META,
            **(dict(attack=1,health=5)if ctype==CardType.MINION else{}))
        r.register_card(definition);r.register_pool_card(PoolCard.from_definition(definition))
    r.register_behavior(NESTED,lambda c:(DiscoverFromPool(c.player_id,INNER,source_id=c.source_id),))
    r.register_behavior(HISTORY,lambda c:(ReplayWholeCards(c.player_id,c.source_id,
        WholeCardHistoryQuery(c.player_id,len(c.state.play_history)+1,kinds=(CardType.MINION,)),
        physical_profile=RETAINED_PROFILE),))
    for cid in (NESTED,HISTORY):
        definition=CardDefinition(cid,cid,CardType.SPELL,cost=4,on_play=cid,metadata=META)
        r.register_card(definition);r.register_pool_card(PoolCard.from_definition(definition))
    variant=KINDS[kind]
    for pool,members in ((POOL,(SKIP,variant)),(INNER,(SKIP,MIN))):
        r.register_pool(PoolDefinition(pool,'v1',CONTEXT.target_id,CONTEXT.mode,
            tuple(PoolMember(cid)for cid in members),complete=True))
    gifts=tuple(g for g in DARK_GIFTS if g.grant.special is None and
        all(g.eligible(r.card(cid))for cid in (SKIP,MIN)))[:3]
    if mode in ('gift_living','gift_living_dormant','gift_repeat'):
        special='living_nightmare'if mode.startswith('gift_living')else'rude_awakening'
        gifts=(next(g for g in DARK_GIFTS if g.grant.special==special),
            next(g for g in DARK_GIFTS if g.id=='EDR_100t1'),
            next(g for g in DARK_GIFTS if g.id=='EDR_100t3'))
    gift_pool=DiscoveryGiftPool(P+'gifts','v1',CONTEXT.target_id,CONTEXT.mode,gifts,complete=True)
    def discover(c):
        if mode.startswith('map'):
            return(DiscoverForPlayFollowup(ChooseFromZone(c.player_id,c.player_id,Zone.DECK,
                operation='copy_base'if mode=='map_base'else'copy_current',source_id=c.source_id,
                distinct='entity',discovery=True)),)
        if mode=='stored':return(DiscoverDeckDarkGift(c.player_id,c.source_id),)
        if mode=='dead':
            options=tuple(ChoiceOption(str(row.id),row.card_id,
                (ResurrectMinion(c.player_id,row.id,source_id=c.source_id,cause=SummonCause.capture(c)),),card_id=row.card_id)
                for row in c.state.death_history if row.card_id in(SKIP,MIN))
            return(RequestChoice(c.player_id,options,c.source_id,purpose=ChoicePurpose.CARD_DISCOVERY),)
        if mode.startswith(('physical','preselected','inactive')):
            return (ChooseFromZone(c.player_id,c.player_id,Zone.DECK,
                operation='copy_base'if mode=='physical_base'else'copy_current',source_id=c.source_id,
                distinct='entity',discovery=True),)
        if kind=='history' or mode in ('single','ordered'):
            from hs_sim.engine.effects import AddToHand
            ids=(SKIP,)if mode=='single'else(SKIP,WEAPON,SPELL)if mode=='ordered'else(variant,SKIP)
            return (RequestChoice(c.player_id,tuple(ChoiceOption(cid,cid,
                (AddToHand(c.player_id,cid,c.source_id),),card_id=cid)for cid in ids),
                c.source_id,purpose=ChoicePurpose.CARD_DISCOVERY),)
        return (DiscoverFromPool(c.player_id,POOL,source_id=c.source_id,
            query=PoolQuery(kinds=(CardType.MINION,),collectible=True)if mode=='temporary'else PoolQuery(),
            gift_pool=gift_pool if mode.startswith('gift')else None,cost=CostSpec(delta=-1)if mode.startswith('gift')else None,
            temporary_until_turn=c.state.turn if mode=='temporary'else None),)
    r.register_behavior(DISC,discover);r.register_card(CardDefinition(DISC,DISC,CardType.SPELL,on_play=DISC))
    def prepare(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==variant)
        ref=CardReference.capture(e)
        if mode.startswith(('preselected','inactive')):
            origins=('hand',)if mode.startswith('inactive')else('hand','physical'if kind=='choose_minion'else'cast_effect')
            return(SetChooseBranch(ref,'both',origins,'strict',c.source_id),)
        gift=next(g for g in DARK_GIFTS if g.grant.special is None and(g.grant.attack>0 or g.grant.health>0)and g.eligible(r.card(variant)))
        return(ModifyStoredCost(ref,CostSpec(delta=-2),c.source_id),GrantDarkGift(ref,gift.id,c.source_id))
    r.register_behavior(PREP,prepare);r.register_card(CardDefinition(PREP,PREP,CardType.SPELL,on_play=PREP))
    r.register_behavior(LOWER,lambda c:(ModifyWeapon(c.state.players[c.player_id].weapon_id,durability=-7,source_id=c.source_id),))
    r.register_card(CardDefinition(LOWER,LOWER,CardType.SPELL,on_play=LOWER))
    r.register_behavior(KILL,lambda c:tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board))
    r.register_card(CardDefinition(KILL,KILL,CardType.SPELL,on_play=KILL))
    hero_kw={}
    if mode in ('wait_spell','wait_minion'):
        event='spell_cast_started'if mode=='wait_spell'else'battlecry_started'
        wanted=SPELL if mode=='wait_spell'else MIN
        r.register_trigger_condition(P+'wait_condition',lambda c:c.event.player_id==c.player_id and c.event.source_id is not None and
            c.state.entities[c.event.source_id].card_id==wanted)
        def transfer_back(c):
            e=c.state.entities[next(i for i,e in c.state.entities.items()if e.card_id==REWARD)]
            return(TransferWeapon(EquippedWeaponReference.capture(e),1,c.source_id),)
        r.register_behavior(P+'back',transfer_back)
        def wait(c):
            weapon=c.state.entities[c.state.players[1].weapon_id];ref=EquippedWeaponReference.capture(weapon)
            return(RequestChoice(1,(ChoiceOption('ok','Continue'),
                ChoiceOption('replace','Replace',(EquipWeapon(1,WEAPON),)),
                ChoiceOption('roundtrip','Transfer out and back',(TransferWeapon(ref,2,c.source_id),InvokeBehavior(P+'back',c.source_id,1))),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(P+'wait',wait)
        hero_kw['limited_triggers']=(LimitedTriggerSpec(event,P+'wait',condition_id=P+'wait_condition'),)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,
        metadata=replace(META,collectible=False),**hero_kw))
    r.validate();r.freeze();return r


def game(kind='minion',mode='plain',hand=None,board=()):
    variant=KINDS[kind]
    hand=(REWARD,DISC)if hand is None else hand
    deck=(SKIP,variant)if mode.startswith(('physical','preselected','inactive','map','stored'))else(SKIP,)*4
    setups=(PlayerSetup(HERO,hand=hand,board=board,deck=deck,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=POWER),
        PlayerSetup(HERO,hand=(DISC,),deck=(SKIP,)*4,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=POWER))
    return Game.from_scenario(Scenario(setups,seed=177,generation_context=CONTEXT),registry(kind,mode))


def first(g,cid,zone='hand',pid=1):
    return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)


def play(g,cid,pid=1):
    e=first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id


def choose(g,key=None):
    q=g.state.pending_choice;o=next(o for o in q.options if o.id==key or key is None and o.card_id==SKIP)
    g.apply(SelectChoice(q.player_id,q.id,(o.id,)))


class OriginStoneTests(unittest.TestCase):
    def negative(self,g,mutate,kind='minion',mode='plain'):
        from hs_sim.engine.serialization import canonical_hash
        good=g.snapshot();bad=deepcopy(good);mutate(bad)
        bad['state_hash']=canonical_hash({k:v for k,v in bad.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as caught:
            Game.from_snapshot(bad,registry(kind,mode,'reader'))
        self.assertNotIn('digest mismatch',str(caught.exception));self.assertEqual(g.snapshot(),good)

    def portable(self,g,kind='minion',mode='plain'):
        reader=registry(kind,mode,'reader');self.assertIsNot(reader,g.registry);saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        for pid in(1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for word in('whole_card_replay_ledger','original_offer','resolution_frame','rng_state','original_discovery_offer'):
                self.assertNotIn('"'+word+'"',visible)

    def test_a0_native_quest_completes_exactly_eight_real_discoveries_and_creates_reward_once(self):
        g=game(hand=(CARD,)+(DISC,)*8);source=play(g,CARD)
        for n in range(8):
            play(g,DISC);choose(g)
            if n<7:self.assertEqual(g.state.entities[source].quest_progress.value,n+1)
        self.assertEqual(sum(g.state.entities[i].card_id==REWARD for i in g.state.players[1].hand),1)
        self.assertEqual(len(g.state.card_discovery_history),8);self.assertEqual(g.state.whole_card_replay_ledger.roots,())
        self.assertEqual(g.state.players[1].mana,59);self.portable(g)

    def test_b0_all_five_native_full_bodies_without_extra_hand_payment_or_fake_plays(self):
        for kind in('minion','spell','weapon','location','hero'):
            with self.subTest(kind=kind):
                g=game(kind);weapon=play(g,REWARD);play(g,DISC);choose(g)
                ledger=g.state.whole_card_replay_ledger;root,=ledger.roots;child,=ledger.children
                self.assertIsInstance(root.selection,OfferedCardSelection);self.assertEqual(child.card_id,KINDS[kind])
                self.assertEqual(root.status,'finished');self.assertEqual(g.state.players[1].mana,57)
                self.assertEqual(len(g.state.play_history),2);self.assertEqual(g.state.entities[weapon].durability,8 if kind=='weapon' else 7)
                self.assertFalse(any(e.card_id==SKIP and e.zone==Zone.BOARD for e in g.state.entities.values()))
                if kind=='minion':self.assertEqual((first(g,MIN,'board').attack,g.state.entities[g.state.players[1].hero_id].armor),(3,3))
                if kind=='spell':self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28)
                if kind=='weapon':self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id,WEAPON);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
                if kind=='location':self.assertEqual(first(g,LOCATION,'board').durability,2);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
                if kind=='hero':self.assertEqual(g.state.entities[g.state.players[1].hero_id].card_id,HERO_CARD);self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,POWER2);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,9)
                self.portable(g,kind)

    def test_b1_single_option_discovery_plays_nothing_but_wears_original_weapon_once(self):
        g=game(mode='single');weapon=play(g,REWARD);play(g,DISC);rng=g.snapshot()['rng_state'];choose(g)
        self.assertEqual(g.state.whole_card_replay_ledger.children,());self.assertEqual(g.state.entities[weapon].durability,7)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g,mode='single')

    def test_c0_current_physical_material_preserves_original_gift_and_cost_without_moving_deck_cards(self):
        # The preparation is a normal stored-card action, then discovery copies
        # both references; the unselected original stays in the real deck.
        g=game(mode='physical',hand=(REWARD,PREP,DISC));play(g,REWARD);play(g,PREP)
        original=first(g,MIN,'deck');ids=list(g.state.players[1].deck);play(g,DISC);choose(g)
        copy=first(g,MIN,'board');self.assertNotEqual(copy.id,original.id)
        self.assertEqual(g.state.players[1].deck,ids);self.assertEqual((copy.attack,copy.max_health),(original.attack,original.max_health))
        self.assertEqual(local_cost(copy),local_cost(original));self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,original.attack)
        self.portable(g,mode='physical')

    def test_b2_original_ordered_batch_finishes_after_first_option_replaces_stone(self):
        g=game(mode='ordered');old=play(g,REWARD);play(g,DISC);choose(g)
        self.assertEqual([c.card_id for c in g.state.whole_card_replay_ledger.children],[WEAPON,SPELL])
        new=g.state.entities[g.state.players[1].weapon_id]
        self.assertEqual((new.card_id,new.durability),(WEAPON,3));self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28);self.portable(g,mode='ordered')

    def test_b3_last_durability_breaks_original_stone_even_when_minion_has_no_space(self):
        g=game(hand=(REWARD,LOWER,DISC),board=(MIN,)*7);weapon=play(g,REWARD);play(g,LOWER)
        self.assertEqual(g.state.entities[weapon].durability,1);play(g,DISC);choose(g)
        self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(g.state.entities[weapon].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(g.state.whole_card_replay_ledger.children[-1].physical.failure,'board_full');self.portable(g)

    def test_c1_base_physical_offer_keeps_printed_body_even_when_original_has_current_modifiers(self):
        g=game(mode='physical_base',hand=(REWARD,PREP,DISC));play(g,REWARD);play(g,PREP);play(g,DISC);choose(g)
        copy=first(g,MIN,'board');self.assertEqual((copy.attack,copy.max_health,local_cost(copy)[0]),(3,4,4));self.portable(g,mode='physical_base')

    def test_c2_intrinsic_gift_travels_but_selected_only_discount_does_not(self):
        g=game(mode='gift');play(g,REWARD);play(g,DISC);choose(g)
        row,=g.state.card_discovery_history;offer=offer_for_result(g,row.result)
        branch=next(o.effects[0]for o in offer.options if o.card_id==MIN);gift=branch.selection.gift
        copy=first(g,MIN,'board');self.assertEqual((copy.attack,copy.max_health),(3+gift.grant.attack,4+gift.grant.health))
        self.assertEqual(local_cost(copy)[0],max(0,4+gift.cost_delta));self.portable(g,mode='gift')

    def test_c3_map_current_and_base_follow_original_request_and_reward_does_not_discover_again(self):
        for mode in('map_current','map_base'):
            g=game(mode=mode,hand=(REWARD,PREP,DISC));weapon=play(g,REWARD);play(g,PREP)
            original=first(g,MIN,'deck');play(g,DISC);choose(g);copy=first(g,MIN,'board')
            self.assertEqual(copy.attack,original.attack if mode=='map_current' else 3)
            play(g,SKIP);choose(g,g.state.pending_choice.options[0].id)
            self.assertEqual(len(g.state.card_discovery_history),1);self.assertEqual(g.state.entities[weapon].durability,7)
            self.portable(g,mode=mode)

    def test_c4_stored_gift_original_uses_frozen_local_material_and_its_own_gift(self):
        g=game(mode='stored',hand=(REWARD,PREP,DISC));play(g,REWARD);play(g,PREP);original=first(g,MIN,'deck')
        play(g,DISC);offer=g._frame.original_discovery_offer
        branch=next(o.effects[0]for o in offer.options if o.card_id==MIN)
        from hs_sim.engine.stored_gift_discovery import gift_by_id
        gift=gift_by_id(branch.offered[branch.index].gift_id);choose(g)
        child,=g.state.whole_card_replay_ledger.children;copy=g.state.entities[child.physical.source.entity_id]
        self.assertNotEqual(copy.id,original.id);self.assertEqual(g.state.entities[original.id].zone,Zone.DECK)
        self.assertEqual((copy.attack,copy.max_health),(max(0,original.attack+gift.grant.attack),original.max_health+gift.grant.health))
        self.portable(g,mode='stored')

    def test_c5_original_death_offers_play_a_fresh_full_body_without_borrowing_the_old_corpse(self):
        g=game(mode='dead',hand=(REWARD,KILL,DISC),board=(SKIP,MIN));play(g,REWARD)
        originals=set(g.state.players[1].board);play(g,KILL);play(g,DISC);choose(g)
        primary=first(g,MIN,'board');self.assertNotIn(primary.id,originals)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3)
        self.assertEqual(len(g.state.card_discovery_history),1);self.portable(g,mode='dead')

    def test_c6_temporary_delivery_is_selected_only_and_does_not_expire_played_other_option(self):
        g=game(mode='temporary');weapon=play(g,REWARD);play(g,DISC);choose(g)
        self.assertIsNotNone(first(g,SKIP).hand_lifetime);other=first(g,MIN,'board')
        self.assertIsNone(other.hand_lifetime);g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[other.id].zone,Zone.BOARD);self.assertEqual(g.state.entities[weapon].durability,7)
        self.portable(g,mode='temporary')

    def test_c7_living_nightmare_uses_real_generated_body_and_extra_copy_is_not_played_again(self):
        for mode in('gift_living','gift_living_dormant'):
            g=game(mode=mode);weapon=play(g,REWARD);play(g,DISC);offer=g._frame.original_discovery_offer
            living=next(o for o in offer.options if o.effects[0].selection.gift.grant.special=='living_nightmare')
            selected=next(o for o in offer.options if o.id!=living.id);choose(g,selected.id)
            self.assertEqual(len(g.state.players[1].board),2);self.assertEqual(len(g.state.whole_card_replay_ledger.children),1)
            self.assertEqual(g.state.entities[weapon].durability,7)
            source=g.state.whole_card_replay_ledger.children[0].physical.source.entity_id
            extra=next(g.state.entities[i]for i in g.state.players[1].board if i!=source)
            self.assertEqual((extra.card_id,extra.attack,extra.max_health),(living.card_id,2,2))
            if mode=='gift_living_dormant':self.assertIsNotNone(extra.dormancy);self.assertIsNotNone(g.state.entities[source].dormancy)
            self.portable(g,mode=mode)

    def test_c8_rude_awakening_reuses_actual_generated_battlecry_repeat_plan(self):
        g=game(mode='gift_repeat');weapon=play(g,REWARD);play(g,DISC);choose(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,6)
        self.assertEqual(g.state.entities[weapon].durability,7);self.assertEqual(len(g.state.battlecry_history),2)
        self.portable(g,mode='gift_repeat')

    def test_d0_nested_discoveries_have_distinct_sources_and_each_wears_after_its_own_batch(self):
        g=game('nested');weapon=play(g,REWARD);play(g,DISC);choose(g)
        self.assertEqual(len(g.state.card_discovery_history),2);ledger=g.state.whole_card_replay_ledger
        self.assertEqual(len(ledger.roots),2);self.assertTrue(all(c.failure is None for c in ledger.children))
        self.assertEqual(g.state.entities[weapon].durability,6);self.assertEqual(ledger.stack,());self.portable(g,'nested')

    def test_d1_real_nested_history_slot_one_is_not_the_same_as_offered_slot_one(self):
        g=game('history',hand=(MIN,REWARD,DISC));play(g,MIN);weapon=play(g,REWARD);play(g,DISC);choose(g)
        children=g.state.whole_card_replay_ledger.children;self.assertEqual([c.occurrence_id for c in children],[1,1])
        self.assertTrue(all(c.failure is None for c in children));self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,6)
        self.assertEqual(g.state.entities[weapon].durability,7);self.portable(g,'history')

    def test_e0_spell_waiting_restores_rolls_back_and_then_finishes_original_body_and_wear(self):
        g=game('spell','wait_spell');weapon=play(g,REWARD);play(g,DISC);choose(g);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g,'spell','wait_spell');saved=g.snapshot()
        with self.assertRaises(ResolutionError):choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);choose(g,'ok');self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[weapon].durability,7)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28);self.portable(g,'spell','wait_spell')

    def test_e1_replacement_during_wait_does_not_wear_the_new_weapon(self):
        g=game('spell','wait_spell');old=play(g,REWARD);play(g,DISC);choose(g);choose(g,'replace')
        self.assertIsNone(g.state.pending_choice)
        new=g.state.entities[g.state.players[1].weapon_id];self.assertEqual((new.card_id,new.durability),(WEAPON,3))
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28)
        self.portable(g,'spell','wait_spell')

    def test_e2_same_weapon_id_transfer_roundtrip_does_not_rebind_original_wear(self):
        g=game('spell','wait_spell');old=play(g,REWARD);epoch=g.state.entities[old].zone_epoch;play(g,DISC);choose(g);choose(g,'roundtrip')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28)
        self.assertEqual(g.state.players[1].weapon_id,old);self.assertGreater(g.state.entities[old].zone_epoch,epoch)
        self.assertEqual(g.state.entities[old].durability,8);self.portable(g,'spell','wait_spell')

    def test_e3_physical_battlecry_waiting_preserves_actual_installation_and_owed_wear(self):
        g=game('minion','wait_minion');old=play(g,REWARD);play(g,DISC);choose(g);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g,'minion','wait_minion');choose(g,'ok');self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[old].durability,7)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3);self.portable(g,'minion','wait_minion')

    def test_f0_current_saved_choice_keeps_activation_scope_and_combination_policy(self):
        for kind in('choose_spell','choose_minion'):
            for mode in('preselected','inactive'):
                with self.subTest(kind=kind,mode=mode):
                    g=game(kind,mode,hand=(REWARD,PREP,DISC));play(g,REWARD);play(g,PREP);original=first(g,KINDS[kind],'deck')
                    play(g,DISC);choose(g);armor=g.state.entities[g.state.players[1].hero_id].armor
                    self.assertEqual(armor,33)if mode=='preselected'else self.assertIn(armor,(11,22))
                    child,=g.state.whole_card_replay_ledger.children
                    entity=g.state.entities[g.state.cast_history[child.spell_cast_id-1].source_id]if child.kind==CardType.SPELL else first(g,KINDS[kind],'board')
                    self.assertEqual(entity.choose_branch,original.choose_branch);self.portable(g,kind,mode)

    def test_f1_failed_played_body_returns_to_exact_original_pending_discovery(self):
        g=game('spell','fail_body');weapon=play(g,REWARD);play(g,DISC);saved=g.snapshot()
        with self.assertRaises(ResolutionError):choose(g)
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.state.entities[weapon].durability,8)
        self.assertEqual(g.state.whole_card_replay_ledger.roots,());self.portable(g,'spell','fail_body')

    def test_f2_opponent_discovery_does_not_trigger_my_stone(self):
        g=game();weapon=play(g,REWARD);g.apply(EndTurn(1));play(g,DISC,2);choose(g)
        self.assertEqual(g.state.entities[weapon].durability,8);self.assertEqual(g.state.whole_card_replay_ledger.roots,());self.portable(g)

    def test_g0_rehashed_complete_source_cannot_trim_reorder_or_replace_original_menu(self):
        g=game();play(g,REWARD);play(g,DISC);choose(g)
        def selection(s):return s['state']['whole_card_replay_ledger']['roots'][0]['selection']
        self.negative(g,lambda s:selection(s)['rows'].reverse())
        self.negative(g,lambda s:selection(s)['rows'].pop())
        self.negative(g,lambda s:selection(s)['discovery'].update(id=2))
        self.negative(g,lambda s:selection(s)['discovery']['result']['choice'].update(id=99))
        self.portable(g)

    def test_g1_rehashed_offered_child_cannot_erase_body_or_claim_historical_branch_policy(self):
        g=game('spell','wait_spell');play(g,REWARD);play(g,DISC);choose(g)
        def ledger(s):return s['state']['whole_card_replay_ledger']
        self.negative(g,lambda s:ledger(s)['roots'][0].update(spell_branch_policy='current'),'spell','wait_spell')
        self.negative(g,lambda s:ledger(s)['children'][0].update(spell_cast_id=None),'spell','wait_spell')
        self.portable(g,'spell','wait_spell');choose(g,'ok');self.assertIsNone(g.state.pending_choice);self.portable(g,'spell','wait_spell')

    def test_z0_full_native_source_registration_and_old_schema_rejection(self):
        from hs_sim.cards.native_origin_stone_cards import load_batch
        from tools.card_batch import check_face
        d=load_batch();rows={x['record']['id']:x['record']for x in d['cards']+d['dependencies']}
        for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'])
        self.assertEqual(len(d['exact_parent_child_links']),2)
        g=game();saved=g.snapshot();saved['schema_version']=380
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry('minion','plain','reader'))


if __name__=='__main__':unittest.main()
