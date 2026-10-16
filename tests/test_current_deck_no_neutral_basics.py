"""Finite current-deck predicate and one necessary DMF_241 native adapter."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    CheckDeckCondition, DeckCondition, DeckSpec, EndTurn, Game, Keyword, MatchSetup,
    PlayCard, PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError,
    UnknownDeckFacts, matches_deck_condition)
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Draw, GainArmor,
    GrantKeyword, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck, CardReference, DestroyDeckMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE='DMF_241';CONDITION=DeckCondition('current','no_neutral')
SUPPORT=Path(__file__).resolve().parents[1]/'data/support/current-deck-no-neutral-basics.json'
PIN='84e0409f373c911d4842aac18d91df3cb219140e26d3451daaf9d2abfd64bb6e'
KEYWORDS=(Keyword.RUSH,Keyword.LIFESTEAL,Keyword.TAUNT,Keyword.DIVINE_SHIELD)


def evidence():
    value=json.loads(SUPPORT.read_bytes())
    if canonical_digest(value)!=PIN or len(value['records'])!=1:raise ValueError('Complete no-Neutral evidence changed')
    row=value['records'][0]
    if row['id']!=NATIVE or canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Complete DMF_241 row changed')
    return row['data']


def branch(player=1,yes=(3,),no=(1,)):
    return CheckDeckCondition(player,CONDITION,tuple(GainArmor(player,n) for n in yes),tuple(GainArmor(player,n) for n in no))


def pause(player=1):return RequestChoice(player,(ChoiceOption('ok','Continue',()),))


def registry():
    r=opening_registry();raw=evidence()
    r.register_behavior('native.no_neutral',lambda c:(CheckDeckCondition(c.player_id,CONDITION,
        tuple(GrantKeyword(c.source_id,k,source_id=c.source_id) for k in KEYWORDS)),))
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        battlecry='native.no_neutral',metadata=metadata_from_record(raw)))
    for i in range(1,31):
        r.register_card(CardDefinition(f'class.{i}','Reviewed Paladin fixture',CardType.MINION,cost=1,attack=1,health=4,
            metadata=metadata(CardClass.PALADIN)))
    r.register_card(CardDefinition('dual','Dual class',CardType.MINION,health=3,
        metadata=CardMetadata(True,(CardClass.PALADIN,CardClass.MAGE),Rarity.COMMON)))
    r.register_card(CardDefinition('foreign','Foreign class',CardType.MINION,health=3,metadata=metadata(CardClass.MAGE)))
    r.register_card(CardDefinition('neutral.token','Uncollectible Neutral',CardType.MINION,health=3,metadata=metadata(collectible=False)))
    r.register_card(CardDefinition('hidden.exact.face','Unknown metadata fixture',CardType.MINION,health=3))
    for cid,kind,meta in (('neutral.spell',CardType.SPELL,metadata()),('class.spell',CardType.SPELL,metadata(CardClass.PALADIN))):
        r.register_card(CardDefinition(cid,cid,kind,metadata=meta))
    for cid,meta in (('class.alias.a',metadata(CardClass.PALADIN,deck_identity='shared')),
                     ('class.alias.b',metadata(CardClass.PALADIN,deck_identity='shared')),
                     ('neutral.alias',metadata(deck_identity='shared'))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=3,metadata=meta))
    r.register_card(CardDefinition('paladin.power','Reviewed Paladin fixture power',CardType.HERO_POWER,cost=2,
        on_use='power',metadata=metadata(CardClass.PALADIN,collectible=False)))
    r.register_card(CardDefinition('paladin.hero','Reviewed Paladin fixture hero',CardType.HERO,health=30,
        initial_hero_power='paladin.power',metadata=metadata(CardClass.PALADIN,collectible=False)))
    first_deck=lambda c:CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]])
    native_board=lambda c:next(e for e in c.state.players[c.player_id].board if c.state.entities[e].card_id==NATIVE)
    scripts={
        'draw':lambda c:(Draw(c.player_id),),
        'shuffle':lambda c:(AddToDeck(c.player_id,'card.1'),),
        'clear':lambda c:(DestroyDeckMatching(c.player_id,count=30,reveal=False),),
        'to.neutral':lambda c:(TransformCapturedMinion(first_deck(c),'card.1'),),
        'to.class':lambda c:(TransformCapturedMinion(first_deck(c),'class.1'),),
        'silence':lambda c:(Silence(native_board(c)),),
        'bounce':lambda c:(ReturnToHand(native_board(c)),),
        'check':lambda c:(branch(c.player_id),),
        'before.wait':lambda c:(pause(c.player_id),Draw(c.player_id),branch(c.player_id)),
        'selected.yes':lambda c:(CheckDeckCondition(c.player_id,CONDITION,
            (pause(c.player_id),AddToDeck(c.player_id,'card.1'),GainArmor(c.player_id,3)),(GainArmor(c.player_id,1),)),),
        'selected.no':lambda c:(CheckDeckCondition(c.player_id,CONDITION,(GainArmor(c.player_id,3),),
            (pause(c.player_id),Draw(c.player_id),GainArmor(c.player_id,1))),),
        'fail':lambda c:(branch(c.player_id),AddToHand(c.player_id,'unknown.no_neutral.delivery')),
    }
    for cid,fn in scripts.items():
        r.register_behavior(cid,fn);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata(CardClass.PALADIN)))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
    return saved


class CurrentDeckNoNeutralTests(unittest.TestCase):
    def game(self,hand=(NATIVE,),deck=(),*,other_deck=(),other_hand=(),board=(),other_board=()):
        return Game.from_scenario(Scenario((PlayerSetup('paladin.hero',hand=hand,deck=deck,board=board,
            hero_power_card_id='paladin.power',mana=10,max_mana=10),PlayerSetup('warrior.hero',hand=other_hand,
            deck=other_deck,board=other_board,hero_power_card_id='warrior.power',mana=10,max_mana=10)),seed=78),registry())
    def play(self,g,cid=NATIVE):
        player=g.state.active_player;identity=next(e for e in g.state.players[player].hand if g.state.entities[e].card_id==cid)
        g.apply(PlayCard(player,identity));return identity
    def query(self,g,player=1):return matches_deck_condition(g.state,g.registry,player,CONDITION)
    def native(self,g,player=1):return next(g.state.entities[e] for e in g.state.players[player].board if g.state.entities[e].card_id==NATIVE)
    def armor(self,g,player=1):return g.state.entities[g.state.players[player].hero_id].armor
    def check(self,g):
        saved=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(saved,registry())
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return restored
    def choose(self,g):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
    def nested(self,v,name):
        if isinstance(v,dict):
            if v.get('type','').endswith('.'+name):return v
            for value in v.values():
                result=self.nested(value,name)
                if result:return result
        if isinstance(v,list):
            for value in v:
                result=self.nested(value,name)
                if result:return result
    def reject(self,saved):
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry())

    def test_complete_raw_pin_and_native_stats_class_rarity_tribe(self):
        raw=evidence();card=registry().card(NATIVE)
        self.assertEqual((card.cost,card.attack,card.health),(8,7,5));self.assertEqual(card.metadata,metadata_from_record(raw))
        self.assertEqual((card.metadata.classes,card.metadata.rarity,card.metadata.tribes),((CardClass.PALADIN,),Rarity.LEGENDARY,('draenei',)))
        self.assertIn('no Neutral cards',raw['text_en']);self.assertEqual(card.keywords,())

    def test_class_duplicates_pass_while_no_duplicates_fails(self):
        g=self.game(deck=('class.1','class.1'));self.assertTrue(self.query(g))
        self.assertFalse(matches_deck_condition(g.state,g.registry,1));self.check(g)

    def test_neutral_singleton_fails_while_no_duplicates_passes(self):
        g=self.game(deck=('card.1',));self.assertFalse(self.query(g))
        self.assertTrue(matches_deck_condition(g.state,g.registry,1));self.check(g)

    def test_current_empty_deck_passes_without_inventing_starting_facts(self):
        g=self.game();self.assertTrue(self.query(g));self.assertIsNone(g.state.opening)
        with self.assertRaises(UnknownDeckFacts):matches_deck_condition(g.state,g.registry,1,DeckCondition('starting'))

    def test_neutral_is_independent_of_card_type_collectibility_and_tribe(self):
        for cid,expected in (('neutral.spell',False),('neutral.token',False),('class.spell',True),('dual',True),('foreign',True)):
            with self.subTest(card=cid):self.assertEqual(self.query(self.game(deck=(cid,))),expected)

    def test_requested_player_uses_own_current_deck(self):
        g=self.game(deck=('class.1',),other_deck=('card.1',));self.assertTrue(self.query(g));self.assertFalse(self.query(g,2));self.check(g)

    def test_neutral_hand_and_board_do_not_enter_current_deck_predicate(self):
        g=self.game((NATIVE,'card.1'),deck=('class.1',),board=('card.2',),other_deck=('card.3',));self.assertTrue(self.query(g));self.check(g)

    def test_alias_identity_does_not_deduplicate_class_membership(self):
        g=self.game(deck=('class.alias.a','class.alias.b'));self.assertTrue(self.query(g))
        self.assertFalse(matches_deck_condition(g.state,g.registry,1))
        g=self.game(deck=('class.alias.a','neutral.alias'));self.assertFalse(self.query(g));self.check(g)

    def test_unknown_metadata_is_checked_after_known_neutral_and_not_disclosed(self):
        for deck in (('hidden.exact.face','card.1'),('card.1','hidden.exact.face')):
            g=self.game(deck=deck)
            with self.assertRaises(UnknownDeckFacts) as error:self.query(g)
            self.assertNotIn('hidden.exact.face',str(error.exception));self.check(g)

    def test_query_does_not_change_rng_events_or_physical_state(self):
        g=self.game(deck=('class.1','dual'));before=g.snapshot();self.assertTrue(self.query(g));self.assertEqual(g.snapshot(),before)

    def test_draw_last_neutral_recomputes_current_condition(self):
        g=self.game(('draw',),deck=('card.1','class.1'));self.assertFalse(self.query(g));self.play(g,'draw')
        self.assertTrue(self.query(g));self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id,'card.1');self.check(g)

    def test_shuffling_neutral_changes_current_deck_and_keeps_hand_irrelevant(self):
        g=self.game(('shuffle',),deck=('class.1',));self.assertTrue(self.query(g));self.play(g,'shuffle');self.assertFalse(self.query(g));self.check(g)

    def test_destroying_all_remaining_cards_makes_current_empty_true(self):
        g=self.game(('clear',),deck=('class.1','card.1'));self.assertFalse(self.query(g));self.play(g,'clear')
        self.assertTrue(self.query(g));self.assertEqual(g.state.players[1].deck,[]);self.check(g)

    def test_cross_zone_transform_uses_current_face_not_original_identity(self):
        for before,spell,want in (('class.1','to.neutral',False),('card.1','to.class',True)):
            g=self.game((spell,),deck=(before,));identity=g.state.players[1].deck[0];self.play(g,spell)
            self.assertEqual(g.state.players[1].deck,[identity]);self.assertEqual(self.query(g),want);self.check(g)

    def test_full_thirty_slot_paladin_experimental_constructed_fixture(self):
        r=registry();own=(NATIVE,)+tuple(f'class.{i}' for i in range(1,30));enemy=tuple(f'card.{i}' for i in range(1,31))
        g=Game.from_decks(MatchSetup((DeckSpec('paladin.hero','paladin.power',CardClass.PALADIN,own),
            DeckSpec('warrior.hero','warrior.power',CardClass.WARRIOR,enemy)),policy(r),'coin',78,1),r)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        self.assertEqual(tuple(map(len,g.state.opening.original_entities)),(30,30));self.assertTrue(self.query(g));self.assertFalse(self.query(g,2));self.check(g)

    def test_native_grants_exact_four_existing_keywords_without_stat_bonus(self):
        g=self.game(deck=('class.1','class.1'));self.play(g);e=self.native(g)
        self.assertEqual((e.attack,e.health),(7,5));self.assertEqual(e.keywords,set(KEYWORDS))
        self.assertEqual((g.state.players[1].mana,g.state.play_history[-1].cost),(2,8));self.check(g)

    def test_native_miss_is_still_paid_minion_with_no_grants(self):
        g=self.game(deck=('card.1',));self.play(g);e=self.native(g)
        self.assertEqual((e.attack,e.health),(7,5));self.assertEqual(e.keywords,set());self.assertEqual(g.state.players[1].mana,2);self.check(g)

    def test_native_second_player_uses_execution_player_not_first_player_deck(self):
        g=self.game((),deck=('card.1',),other_deck=('class.1',),other_hand=(NATIVE,));g.apply(EndTurn(1));self.play(g)
        self.assertEqual(self.native(g,2).keywords,set(KEYWORDS));self.assertFalse(self.query(g));self.check(g)

    def test_native_player_command_pays_once_and_uses_original_legal_action(self):
        g=self.game(deck=('class.1',));port=g.for_player(1);dto=port.legal_actions()
        card=next(r for r in g.observe(1)['players'][0]['hand'] if r['card_id']==NATIVE)
        action=next(a for a in dto['actions'] if a.get('card')==card['ref'])
        self.assertTrue(port.submit({'revision':dto['revision'],'action':action})['accepted'])
        self.assertEqual((self.native(g).attack,g.state.players[1].mana),(7,2));self.check(g)

    def test_unknown_metadata_rolls_back_native_payment_entry_and_history(self):
        g=self.game(deck=('card.1','hidden.exact.face'));before=g.snapshot()
        with self.assertRaises(UnknownDeckFacts):self.play(g)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_condition_before_execution_reads_deck_after_wait_and_draw(self):
        g=self.game(('before.wait',),deck=('card.1',));self.play(g,'before.wait');self.assertFalse(self.query(g));restored=self.check(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertTrue(self.query(g));self.assertEqual(self.armor(g),3);self.check(g)

    def test_selected_match_branch_stays_selected_after_wait_and_neutral_shuffle(self):
        g=self.game(('selected.yes',),deck=('class.1',));self.play(g,'selected.yes');restored=self.check(g);clone=g.clone()
        self.assertTrue(self.query(g));self.choose(g)
        for other in (restored,clone):self.choose(other);self.assertEqual(other.snapshot(),g.snapshot())
        self.assertFalse(self.query(g));self.assertEqual(self.armor(g),3);self.check(g)

    def test_selected_miss_branch_stays_selected_after_last_neutral_draw(self):
        g=self.game(('selected.no',),deck=('card.1',));self.play(g,'selected.no');restored=self.check(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertTrue(self.query(g));self.assertEqual(self.armor(g),1);self.check(g)

    def test_unknown_after_wait_rolls_back_to_original_pending_choice(self):
        g=self.game(('before.wait',),deck=('class.1','hidden.exact.face'));self.play(g,'before.wait');before=g.snapshot()
        with self.assertRaises(UnknownDeckFacts):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_late_selected_branch_failure_rolls_back_condition_result(self):
        g=self.game(('fail',),deck=('class.1',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'fail')
        self.assertEqual(g.snapshot(),before)

    def test_typed_condition_codec_has_original_two_fields_and_strict_profile(self):
        g=self.game();codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);wire=codec.encode(CONDITION)
        self.assertEqual(codec.decode(wire),CONDITION);self.assertEqual(set(wire['fields']),{'scope','predicate'})
        for field in ('scope','predicate'):
            bad=deepcopy(wire);del bad['fields'][field]
            with self.assertRaises(ValueError):codec.decode(bad)
        for make in (lambda:DeckCondition('starting','no_neutral'),lambda:DeckCondition('hand','no_neutral'),
                     lambda:DeckCondition('current',True),lambda:DeckCondition('current','no_classes')):
            with self.subTest(make=make),self.assertRaises(ValueError):make()

    def test_waiting_restore_rejects_scope_predicate_and_extra_field_forgery(self):
        g=self.game(('before.wait',),deck=('card.1',));self.play(g,'before.wait')
        for field,value in (('scope','starting'),('predicate','always'),('invented',1)):
            saved=g.snapshot();self.nested(saved['resolution_frame'],'DeckCondition')['fields'][field]=value;self.reject(saved)

    def test_granted_keywords_do_not_retract_after_later_deck_change(self):
        g=self.game((NATIVE,'shuffle'),deck=('class.1',));self.play(g);self.play(g,'shuffle')
        self.assertFalse(self.query(g));self.assertEqual(self.native(g).keywords,set(KEYWORDS));self.check(g)

    def test_silence_and_bounce_clear_grants_then_recheck_on_new_play(self):
        g=self.game((NATIVE,'silence','bounce','shuffle','shuffle'),deck=('class.1',));self.play(g);self.play(g,'silence')
        self.assertEqual(self.native(g).keywords,set());self.play(g,'bounce');self.play(g,'shuffle');self.play(g,'shuffle')
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g)
        self.assertEqual(self.native(g).keywords,set());self.assertEqual((self.native(g).attack,self.native(g).health),(7,5));self.check(g)

    def test_player_views_never_contain_condition_private_deck_inventory(self):
        g=self.game(('before.wait',),deck=('class.29',));self.play(g,'before.wait')
        for player in (1,2):
            text=json.dumps(g.observe(player))+json.dumps(g.player_events(player))+json.dumps(g.for_player(player).legal_actions())
            for value in ('DeckCondition','no_neutral','on_match','on_miss','class.29'):self.assertNotIn(value,text)
        self.check(g)

    def test_wire_layout_schema_stays_while_rule_and_handler_signatures_advance(self):
        g=self.game();self.assertEqual((g.snapshot()['schema_version'],g.ruleset.id,g.mechanics.version),(SNAPSHOT_SCHEMA_VERSION,'prototype-v302',CORE_EFFECTS_VERSION))
        saved=g.snapshot();saved['mechanics_version']['version']='core-effects-v226';self.reject(saved)
        self.check(g)


if __name__=='__main__':unittest.main()
