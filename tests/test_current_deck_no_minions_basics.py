"""Known type-only current-deck condition; one necessary Spell plus its fixed token."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass,CardDefinition,CardType,CheckDeckCondition,DeckCondition,
    DeckSpec,EndTurn,Game,Keyword,MatchSetup,PlayCard,PlayerSetup,Rarity,ResolutionError,
    Scenario,SelectChoice,SnapshotError,SpellSchool,UnknownDeckFacts)
from hs_sim.engine.deck_conditions import matches_deck_condition
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Draw,GainArmor,InvokeBehavior,RequestChoice,ReturnToHand,Summon)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck,CardReference,DestroyDeckMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata,policy
import test_current_deck_no_neutral_basics as foundation
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE='RLK_211';TOKEN='RLK_211t';CONDITION=DeckCondition('current','no_minions')
SUPPORT=Path(__file__).resolve().parents[1]/'data/support/current-deck-no-minions-basics.json'
PIN='298fb351c58cb711d425e1278bf0363af607107dce11816134550d47744e9e92'


def evidence():
    packet=json.loads(SUPPORT.read_bytes())
    if canonical_digest(packet)!=PIN or [r['id'] for r in packet['records']]!=[NATIVE,TOKEN]:raise ValueError('Complete no-Minions source changed')
    for row in packet['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Complete original source/token changed')
    return {row['id']:row['data'] for row in packet['records']}


def pause(player=1):return RequestChoice(player,(ChoiceOption('ok','Continue',()),))


def branch(player=1):return CheckDeckCondition(player,CONDITION,(GainArmor(player,3),),(GainArmor(player,1),))


def registry():
    r=foundation.registry();raw=evidence()
    r.register_behavior('native.no_minions',lambda c:(Summon(c.player_id,TOKEN),Summon(c.player_id,TOKEN),
        CheckDeckCondition(c.player_id,CONDITION,(Summon(c.player_id,TOKEN),Summon(c.player_id,TOKEN)))))
    spell=raw[NATIVE];token=raw[TOKEN]
    r.register_card(CardDefinition(NATIVE,spell['name'],CardType.SPELL,cost=spell['cost'],on_play='native.no_minions',
        spell_school=SpellSchool.FEL,metadata=metadata_from_record(spell)))
    r.register_card(CardDefinition(TOKEN,token['name'],CardType.MINION,cost=token['cost'],attack=token['attack'],health=token['health'],
        keywords=(Keyword.LIFESTEAL,),metadata=metadata_from_record(token)))
    r.register_card(CardDefinition('demon_hunter.power','Demon Hunter fixture power',CardType.HERO_POWER,cost=1,
        on_use='power',metadata=metadata(CardClass.DEMON_HUNTER,collectible=False)))
    r.register_card(CardDefinition('demon_hunter.hero','Demon Hunter fixture hero',CardType.HERO,health=30,
        initial_hero_power='demon_hunter.power',metadata=metadata(CardClass.DEMON_HUNTER,collectible=False)))
    for i in range(1,31):
        r.register_card(CardDefinition(f'type.spell.{i}','Known Spell fixture',CardType.SPELL,metadata=metadata(CardClass.DEMON_HUNTER)))
    for cid,kind,fields in (('known.no_meta.spell',CardType.SPELL,{}),('known.no_meta.weapon',CardType.WEAPON,{'attack':1,'durability':1}),
                           ('known.no_meta.location',CardType.LOCATION,{'durability':1,'on_use':'power'})):
        r.register_card(CardDefinition(cid,cid,kind,**fields))
    first_deck=lambda c:CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]])
    r.register_behavior('types.late.fail',lambda c:(AddToHand(c.player_id,'unknown.no_minions.delivery'),))
    scripts={
        'types.draw':lambda c:(Draw(c.player_id),),
        'types.shuffle':lambda c:(AddToDeck(c.player_id,'class.1'),),
        'types.clear':lambda c:(DestroyDeckMatching(c.player_id,count=30,reveal=False),),
        'types.minion.face':lambda c:(TransformCapturedMinion(first_deck(c),TOKEN),),
        'types.bounce':lambda c:(ReturnToHand(c.state.players[c.player_id].board[0]),),
        'types.check':lambda c:(branch(c.player_id),),
        'types.before.wait':lambda c:(pause(c.player_id),Draw(c.player_id),branch(c.player_id)),
        'types.selected.yes':lambda c:(CheckDeckCondition(c.player_id,CONDITION,
            (pause(c.player_id),AddToDeck(c.player_id,'class.1'),GainArmor(c.player_id,3)),(GainArmor(c.player_id,1),)),),
        'types.selected.no':lambda c:(CheckDeckCondition(c.player_id,CONDITION,(GainArmor(c.player_id,3),),
            (pause(c.player_id),Draw(c.player_id),GainArmor(c.player_id,1))),),
        'types.fail':lambda c:(branch(c.player_id),AddToHand(c.player_id,'unknown.no_minions.delivery')),
        'types.bad.after.wait':lambda c:(pause(c.player_id),branch(c.player_id),InvokeBehavior('types.late.fail',c.source_id,c.player_id)),
    }
    for cid,fn in scripts.items():
        r.register_behavior(cid,fn);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata(CardClass.DEMON_HUNTER)))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
    return saved


class CurrentDeckNoMinionsTests(unittest.TestCase):
    def game(self,hand=(NATIVE,),deck=(),*,other_deck=(),other_hand=(),board=(),other_board=()):
        return Game.from_scenario(Scenario((PlayerSetup('demon_hunter.hero',hand=hand,deck=deck,board=board,
            hero_power_card_id='demon_hunter.power',mana=10,max_mana=10),PlayerSetup('warrior.hero',hand=other_hand,
            deck=other_deck,board=other_board,hero_power_card_id='warrior.power',mana=10,max_mana=10)),seed=79),registry())
    def play(self,g,cid=NATIVE):
        player=g.state.active_player;i=next(e for e in g.state.players[player].hand if g.state.entities[e].card_id==cid)
        g.apply(PlayCard(player,i));return i
    def query(self,g,player=1):return matches_deck_condition(g.state,g.registry,player,CONDITION)
    def armor(self,g,player=1):return g.state.entities[g.state.players[player].hero_id].armor
    def check(self,g):
        saved=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(saved,registry())
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return restored
    def choose(self,g):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
    def nested(self,value,name):
        if isinstance(value,dict):
            if value.get('type','').endswith('.'+name):return value
            for item in value.values():
                result=self.nested(item,name)
                if result is not None:return result
        elif isinstance(value,list):
            for item in value:
                result=self.nested(item,name)
                if result is not None:return result
    def reject(self,saved):
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry())
    def tokens(self,g,player=1):return [g.state.entities[i] for i in g.state.players[player].board if g.state.entities[i].card_id==TOKEN]

    def test_full_raw_pin_source_school_and_exact_linked_token(self):
        raw=evidence();r=registry();s=r.card(NATIVE);t=r.card(TOKEN)
        self.assertEqual((s.cost,s.kind,s.spell_school,s.metadata.classes,s.metadata.rarity),(5,CardType.SPELL,SpellSchool.FEL,(CardClass.DEMON_HUNTER,),Rarity.RARE))
        self.assertEqual(raw[NATIVE]['tags']['SPELL_SCHOOL'],7)
        self.assertEqual(raw[NATIVE]['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'],raw[TOKEN]['dbf_id'])
        self.assertEqual((t.cost,t.attack,t.health,t.keywords,t.metadata.tribes),(3,3,3,(Keyword.LIFESTEAL,),('demon',)))
        self.assertFalse(t.metadata.collectible);self.assertEqual(t.metadata,metadata_from_record(raw[TOKEN]))

    def test_empty_current_deck_true_without_starting_facts(self):
        g=self.game();self.assertTrue(self.query(g));self.assertIsNone(g.state.opening)
        with self.assertRaises(UnknownDeckFacts):matches_deck_condition(g.state,g.registry,1,DeckCondition('starting'))

    def test_class_minion_differs_from_no_neutral_condition(self):
        g=self.game(deck=('class.1',));self.assertFalse(self.query(g))
        self.assertTrue(matches_deck_condition(g.state,g.registry,1,DeckCondition('current','no_neutral')))

    def test_neutral_spell_differs_from_no_neutral_condition(self):
        g=self.game(deck=('neutral.spell',));self.assertTrue(self.query(g))
        self.assertFalse(matches_deck_condition(g.state,g.registry,1,DeckCondition('current','no_neutral')))

    def test_no_minions_does_not_require_all_spells(self):
        g=self.game(deck=('known.no_meta.spell','known.no_meta.weapon','known.no_meta.location'))
        self.assertTrue(self.query(g));self.check(g)

    def test_known_minion_type_without_class_metadata_is_still_minion(self):
        g=self.game(deck=('hidden.exact.face',));self.assertFalse(self.query(g));self.check(g)

    def test_known_non_minion_type_without_class_metadata_is_decidable(self):
        g=self.game(deck=('known.no_meta.spell',));self.assertTrue(self.query(g));self.check(g)

    def test_other_conditions_keep_required_metadata_and_full_traversal(self):
        g=self.game(deck=('card.1','hidden.exact.face'))
        self.assertFalse(self.query(g))
        for condition in (DeckCondition(),DeckCondition('current','no_neutral')):
            with self.assertRaises(UnknownDeckFacts):matches_deck_condition(g.state,g.registry,1,condition)

    def test_requested_player_uses_current_deck_not_first_player(self):
        g=self.game(deck=('class.1',),other_deck=('known.no_meta.spell',));self.assertFalse(self.query(g));self.assertTrue(self.query(g,2));self.check(g)

    def test_minions_in_hand_or_board_do_not_enter_deck_condition(self):
        g=self.game((NATIVE,'card.1'),deck=('known.no_meta.spell',),board=('class.1',),other_board=('class.2',));self.assertTrue(self.query(g));self.check(g)

    def test_duplicate_alias_and_collectibility_do_not_change_known_types(self):
        for deck,want in ((('class.alias.a','class.alias.b'),False),(('neutral.token',),False),(('known.no_meta.spell','known.no_meta.spell'),True)):
            with self.subTest(deck=deck):self.assertEqual(self.query(self.game(deck=deck)),want)

    def test_unknown_definition_after_minion_is_not_hidden_by_short_circuit(self):
        g=self.game(deck=('class.1','neutral.spell'));state=g.state;state.entities[state.players[1].deck[-1]].card_id='unknown.type.face'
        with self.assertRaises(UnsupportedDefinitionError):matches_deck_condition(state,g.registry,1,CONDITION)

    def test_query_preserves_rng_events_and_state(self):
        g=self.game(deck=('known.no_meta.spell',));before=g.snapshot();self.assertTrue(self.query(g));self.assertEqual(g.snapshot(),before)

    def test_draw_last_minion_changes_current_result(self):
        g=self.game(('types.draw',),deck=('class.1','known.no_meta.spell'));self.assertFalse(self.query(g));self.play(g,'types.draw')
        self.assertTrue(self.query(g));self.check(g)

    def test_shuffling_minion_changes_current_result(self):
        g=self.game(('types.shuffle',),deck=('known.no_meta.spell',));self.assertTrue(self.query(g));self.play(g,'types.shuffle')
        self.assertFalse(self.query(g));self.check(g)

    def test_clear_current_deck_does_not_infer_original_deck(self):
        g=self.game(('types.clear',),deck=('class.1','neutral.spell'));self.play(g,'types.clear');self.assertTrue(self.query(g));self.check(g)

    def test_ordinary_stored_minion_transform_keeps_minion_type_and_physical_identity(self):
        g=self.game(('types.minion.face',),deck=('class.1',));identity=g.state.players[1].deck[0]
        self.play(g,'types.minion.face');self.assertEqual(g.state.players[1].deck,[identity])
        self.assertEqual(g.state.entities[identity].card_id,TOKEN);self.assertFalse(self.query(g));self.check(g)

    def test_full_thirty_slot_demon_hunter_experimental_constructed(self):
        r=registry();own=(NATIVE,)+tuple(f'type.spell.{i}' for i in range(1,30));enemy=tuple(f'card.{i}' for i in range(1,31))
        g=Game.from_decks(MatchSetup((DeckSpec('demon_hunter.hero','demon_hunter.power',CardClass.DEMON_HUNTER,own),
            DeckSpec('warrior.hero','warrior.power',CardClass.WARRIOR,enemy)),policy(r),'coin',79,1),r)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        self.assertEqual(tuple(map(len,g.state.opening.original_entities)),(30,30));self.assertTrue(self.query(g));self.assertFalse(self.query(g,2));self.check(g)

    def test_native_spell_summons_four_exact_printed_tokens_when_deck_has_no_minions(self):
        g=self.game(deck=('known.no_meta.spell',));self.play(g);tokens=self.tokens(g)
        self.assertEqual(len(tokens),4);self.assertEqual(len({e.id for e in tokens}),4)
        self.assertTrue(all((e.attack,e.health,e.owner,e.controller,e.keywords)==(3,3,1,1,{Keyword.LIFESTEAL}) for e in tokens))
        self.assertEqual((g.state.players[1].mana,g.state.play_history[-1].cost),(5,5));self.check(g)

    def test_native_spell_summons_only_two_when_minion_remains(self):
        g=self.game(deck=('class.1',));self.play(g);self.assertEqual(len(self.tokens(g)),2);self.assertEqual(g.state.players[1].mana,5);self.check(g)

    def test_native_spell_known_minion_with_missing_class_metadata_still_summons_two(self):
        g=self.game(deck=('hidden.exact.face',));self.play(g);self.assertEqual(len(self.tokens(g)),2);self.check(g)

    def test_native_second_player_uses_execution_player_deck(self):
        g=self.game((),deck=('class.1',),other_deck=('neutral.spell','neutral.spell'),other_hand=(NATIVE,));g.apply(EndTurn(1));self.play(g)
        self.assertEqual(len(self.tokens(g,2)),4);self.assertTrue(all(e.controller==2 for e in self.tokens(g,2)));self.check(g)

    def test_native_board_capacity_uses_original_summon_failures_and_no_new_tokens(self):
        for count,want in ((6,1),(7,0)):
            with self.subTest(board=count):
                g=self.game(deck=('neutral.spell',),board=('class.1',)*count);self.play(g)
                self.assertEqual(len(self.tokens(g)),want);self.assertEqual(len(g.state.players[1].board),7);self.check(g)

    def test_native_player_command_pays_once_through_original_spell_action(self):
        g=self.game(deck=('neutral.spell',));port=g.for_player(1);dto=port.legal_actions()
        card=next(row for row in g.observe(1)['players'][0]['hand'] if row['card_id']==NATIVE)
        action=next(row for row in dto['actions'] if row.get('card')==card['ref'])
        self.assertTrue(port.submit({'revision':dto['revision'],'action':action})['accepted'])
        self.assertEqual((len(self.tokens(g)),g.state.players[1].mana),(4,5));self.check(g)

    def test_token_bounce_keeps_deck_condition_separate_from_hand_token(self):
        g=self.game((NATIVE,'types.bounce'),deck=('known.no_meta.spell',));self.play(g);self.play(g,'types.bounce')
        self.assertTrue(self.query(g));self.assertIn(TOKEN,[g.state.entities[i].card_id for i in g.state.players[1].hand]);self.check(g)

    def test_condition_before_execution_reads_after_wait_and_last_minion_draw(self):
        g=self.game(('types.before.wait',),deck=('class.1',));self.play(g,'types.before.wait');self.assertFalse(self.query(g));restored=self.check(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),3);self.assertTrue(self.query(g));self.check(g)

    def test_selected_match_branch_retains_result_after_minion_shuffle(self):
        g=self.game(('types.selected.yes',),deck=('known.no_meta.spell',));self.play(g,'types.selected.yes');restored=self.check(g);clone=g.clone()
        self.choose(g)
        for other in (restored,clone):self.choose(other);self.assertEqual(other.snapshot(),g.snapshot())
        self.assertFalse(self.query(g));self.assertEqual(self.armor(g),3);self.check(g)

    def test_selected_miss_branch_retains_result_after_last_minion_draw(self):
        g=self.game(('types.selected.no',),deck=('class.1',));self.play(g,'types.selected.no');restored=self.check(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertTrue(self.query(g));self.assertEqual(self.armor(g),1);self.check(g)

    def test_failed_waiting_continuation_rolls_back_original_choice_and_branch(self):
        g=self.game(('types.bad.after.wait',),deck=('known.no_meta.spell',));self.play(g,'types.bad.after.wait');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_late_branch_failure_rolls_back_action_and_result(self):
        g=self.game(('types.fail',),deck=('known.no_meta.spell',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'types.fail')
        self.assertEqual(g.snapshot(),before)

    def test_typed_two_field_codec_and_restricted_scope_remain_strict(self):
        g=self.game();codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);wire=codec.encode(CONDITION)
        self.assertEqual(codec.decode(wire),CONDITION);self.assertEqual(set(wire['fields']),{'scope','predicate'})
        for field in ('scope','predicate'):
            bad=deepcopy(wire);del bad['fields'][field]
            with self.assertRaises(ValueError):codec.decode(bad)
        for make in (lambda:DeckCondition('starting','no_minions'),lambda:DeckCondition('hand','no_minions'),
                     lambda:DeckCondition('current',True),lambda:DeckCondition('current','no_unknown_types')):
            with self.subTest(make=make),self.assertRaises(ValueError):make()

    def test_pending_restore_rejects_scope_predicate_extra_fields_and_wrong_player(self):
        g=self.game(('types.before.wait',),deck=('class.1',));self.play(g,'types.before.wait')
        for field,value in (('scope','starting'),('predicate','always'),('invented',1)):
            saved=g.snapshot();self.nested(saved['resolution_frame'],'DeckCondition')['fields'][field]=value;self.reject(saved)
        saved=g.snapshot();self.nested(saved['resolution_frame'],'CheckDeckCondition')['fields']['player_id']=True;self.reject(saved)

    def test_player_views_hide_condition_and_complete_deck_inventory(self):
        g=self.game(('types.before.wait',),deck=('type.spell.29',));self.play(g,'types.before.wait')
        for player in (1,2):
            text=json.dumps(g.observe(player))+json.dumps(g.player_events(player))+json.dumps(g.for_player(player).legal_actions())
            for name in ('DeckCondition','no_minions','on_match','on_miss','type.spell.29'):self.assertNotIn(name,text)
        self.check(g)

    def test_wire_schema_preserved_and_old_handler_version_rejected(self):
        g=self.game();self.assertEqual((g.snapshot()['schema_version'],g.ruleset.id,g.mechanics.version),(266,'prototype-v302',CORE_EFFECTS_VERSION))
        saved=g.snapshot();saved['mechanics_version']['version']='core-effects-v227';self.reject(saved);self.check(g)


if __name__=='__main__':unittest.main()
