"""Real printed Trade/Prepare halves use ordinary physical-card operations."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_hand_action_prefix_fragments import SOURCES,load_batch,register_assemble_hand_action_prefix_fragments
from hs_sim.cards.native_assemble_entry_cards import FETCHER,NURTURER,CARETAKER,POOL_ID
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,HandActionSpec,IllegalAction,PlayCard,PlayerSetup,
    Scenario,SelectChoice,SnapshotError,TriggerSpec,UseHandAction,Zone)
from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleRecipe
from hs_sim.engine.effects import ChoiceOption,Draw,EquipWeapon,GainArmor,InvokeBehavior,RequestChoice,ShuffleIntoDeck
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import Keyword
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,CopyCard
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import (fixture as base_fixture,META,DECK,COIN,UNIT,KILL,BOUNCE,WATCH as DRAW_WATCH)

TRADE,PREP=SOURCES
CURATOR,CAIRNE,LOOT,EMBER,SELF='CORE_KAR_061','CORE_EX1_110','CORE_EX1_096','TLC_249','CATA_304'
P='fixture.assemble_hand_action.'
EQUIP,WEAPON,COPY_HAND,SHUFFLE,PREP_WATCH,FAULT=(P+x for x in ('equip','weapon','copy','shuffle','watch','fault'))
CTX=GenerationContext('k401-real-printed-hand-action-fixture','experimental')
TRADE_SPEC,PREP_SPEC=HandActionSpec('trade','trade',1),HandActionSpec('prepare','prepare',1)


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__();r._version+='.k401.'+mode
    def prepared(c):return next(e for e in c.state.entities.values()if e.zone==Zone.HAND and e.preparation is not None)
    bodies={EQUIP:lambda c:(EquipWeapon(2,WEAPON),),
        COPY_HAND:lambda c:(CopyCard(CardReference.capture(prepared(c)),c.player_id,Zone.HAND),),
        SHUFFLE:lambda c:(ShuffleIntoDeck(prepared(c).id),Draw(c.player_id,1),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,attack=2,durability=3,metadata=META))
    def fault(c):raise ResolutionError('deliberate assembled Prepare observer fault')
    r.register_behavior(FAULT,fault)
    def watch(c):
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('fault','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(PREP_WATCH,watch)
    r.register_card(CardDefinition(PREP_WATCH,PREP_WATCH,CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('card_prepared',PREP_WATCH),)))
    members=(PREP,CURATOR,CAIRNE)if mode=='fetcher'else (TRADE,SELF,CURATOR)if mode=='trade_native'else (EMBER,TRADE,LOOT)
    if mode=='missing':r._assemble_templates.pop(TRADE)
    if mode!='no_pool':
        r.register_pool(PoolDefinition(POOL_ID,'three-real-hand-action-sources-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(x)for x in members),complete=True))
    return r


class AssembleHandActionPrefixTests(unittest.TestCase):
    def game(self,hand=(),board=(),deck=DECK,mode='normal',hero='HERO_02',mana=30):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=deck,mana=mana,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30)),
            seed=401,generation_context=CTX),fixture(mode))

    def entity(self,g,cid):return next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.entity(g,cid);g.apply(PlayCard(1,eid,target_id=target));return eid
    def use(self,g,eid,kind):return g.apply(UseHandAction(1,eid,kind))
    def next_turn(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))

    def portable(self,g):
        reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry)
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved

    def choose(self,g,primary,secondary,half):
        cid=AssembleRecipe(primary,secondary,half).card_id;q=g.state.pending_choice
        option=next(x for x in q.options if x.card_id==cid)
        g.apply(SelectChoice(q.player_id,q.id,(option.id,)));return cid

    def test_two_complete_sources_four_full_primary_faces_and_exact_original_hand_actions(self):
        data=load_batch();r=build_registry();rows={x['record']['id']:x for x in data['existing_dependencies']}
        self.assertEqual(tuple(rows),SOURCES);self.assertEqual(len(data['official_observations']),4);seen=set()
        for obs in data['official_observations']:
            row=rows[obs['card_id']];check_face(row['record'],obs['face'],obs['locale']);path=Path(obs['response_file'])
            self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([x for x in json.loads(path.read_text('utf-8-sig'))['cards']if x['id']==row['record']['dbf_id']],[obs['face']])
            seen.add((obs['card_id'],obs['locale']))
        self.assertEqual(seen,{(cid,loc)for cid in SOURCES for loc in ('zh_CN','en_US')})
        for cid,row in rows.items():
            self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(r.card(TRADE).hand_actions,(TRADE_SPEC,));self.assertEqual(r.card(PREP).hand_actions,(PREP_SPEC,))
        with self.assertRaises(UnsupportedDefinitionError):r.pool(POOL_ID,CTX)

    def test_whole_sources_reconstruct_and_secondary_body_does_not_leak_its_hand_action(self):
        r=build_registry()
        for source in SOURCES:
            d=r.card(source);same=r.card(AssembleRecipe(source,source,'top').card_id)
            self.assertEqual(asdict(d)|{'id':same.id},asdict(same))
            body=r.card(AssembleRecipe(LOOT,source,'bottom').card_id)
            self.assertEqual(body.hand_actions,());self.assertEqual(body.cost,r.card(LOOT).cost)
            top=r.card(AssembleRecipe(LOOT,source,'top').card_id)
            self.assertEqual(top.hand_actions,d.hand_actions);self.assertEqual(top.cost,r.card(LOOT).cost)

    def test_prefix_rejects_unreviewed_forge_extra_fees_rules_bodies_multiple_or_mutable_actions(self):
        invalid=[[],('trade',),(TRADE_SPEC,PREP_SPEC),(HandActionSpec('forge','forge',2,'GAME_005'),),
            (replace(TRADE_SPEC,cost=2),),(replace(TRADE_SPEC,id='different'),),
            (replace(TRADE_SPEC,on_use='extra'),),(replace(TRADE_SPEC,use_rule='other'),)]
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(ValueError):AssemblePrefix('battlecry',hand_actions=value)
        r=build_registry();t=r.assemble_templates[TRADE];r._assemble_templates.pop(TRADE)
        with self.assertRaises(ValueError):r.register_assemble_template(replace(t,prefix=replace(t.prefix,hand_actions=())))

    def test_real_beast_source_trade_pays_one_keeps_new_face_and_draws_another_physical_card(self):
        g=self.game(hand=(CARETAKER,),mode='trade_native',hero='HERO_09');self.play(g,CARETAKER)
        cid=self.choose(g,TRADE,CURATOR,'bottom');eid=self.entity(g,cid)
        self.assertEqual(g.quote_cost(eid).amount,3);self.assertEqual(g.quote_hand_action(eid,'trade').amount,1)
        before=g.state.players[1].mana;self.use(g,eid,'trade')
        self.assertEqual(g.state.players[1].mana,before-1);self.assertIn(eid,g.state.players[1].deck)
        self.assertEqual(g.state.entities[eid].card_id,cid);self.assertEqual(len(g.state.draw_history),1)
        self.assertNotEqual(g.state.draw_history[0].entity_id,eid)
        self.assertFalse(any(g.state.entities[i].card_id==cid for i in g.state.players[1].board));self.portable(g)

    def test_real_nurturer_transfers_trade_prefix_but_borrowing_weapon_body_does_not_grant_trade(self):
        g=self.game(hand=(NURTURER,));self.play(g,NURTURER);cid=self.choose(g,EMBER,TRADE,'top')
        eid=self.entity(g,cid);self.assertEqual(g.registry.card(cid).cost,1);self.assertIn(UseHandAction(1,eid,'trade'),g.legal_actions())
        self.use(g,eid,'trade');self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        g=self.game(hand=(NURTURER,EQUIP,KILL));self.play(g,EQUIP);weapon=g.state.players[2].weapon_id
        self.play(g,NURTURER);cid=self.choose(g,EMBER,TRADE,'bottom');eid=self.entity(g,cid)
        self.assertNotIn(UseHandAction(1,eid,'trade'),g.legal_actions());self.play(g,cid)
        self.assertEqual(g.state.players[2].weapon_id,weapon);self.play(g,KILL,eid);self.assertIsNone(g.state.players[2].weapon_id)

    def test_real_fetcher_prepare_investment_does_not_play_or_draw_until_later_turn(self):
        g=self.game(hand=(FETCHER,),board=(UNIT,),mode='fetcher');self.play(g,FETCHER)
        cid=self.choose(g,PREP,CURATOR,'bottom');eid=self.entity(g,cid);mana=g.state.players[1].mana
        self.use(g,eid,'prepare');self.assertEqual(g.state.players[1].mana,mana-3)
        self.assertEqual(g.quote_cost(eid).amount,0);self.assertIn(eid,g.state.players[1].hand);self.assertFalse(g.state.draw_history)
        saved=g.snapshot()
        for action in(PlayCard(1,eid),UseHandAction(1,eid,'prepare')):
            with self.assertRaises(IllegalAction):g.apply(action)
            self.assertEqual(g.snapshot(),saved)
        self.next_turn(g);before=len(g.state.draw_history);self.play(g,cid)
        self.assertEqual(len(g.state.draw_history)-before,3);self.assertIn(eid,g.state.players[1].board)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].health,20)

    def test_borrowed_prepare_prices_the_new_two_cost_primary_not_the_four_cost_donor(self):
        cid=AssembleRecipe(LOOT,PREP,'top').card_id;g=self.game(hand=(cid,));eid=self.entity(g,cid)
        self.assertEqual(g.quote_hand_action(eid,'prepare').amount,1);before=g.state.players[1].mana
        self.use(g,eid,'prepare');self.assertEqual(g.state.players[1].mana,before-1);self.assertEqual(g.quote_cost(eid).amount,0)
        self.next_turn(g);drawn=len(g.state.draw_history);self.play(g,cid);self.assertEqual(len(g.state.draw_history)-drawn,1)

    def test_replacing_prepare_prefix_removes_operation_and_defers_old_buff_to_death(self):
        cid=AssembleRecipe(PREP,CAIRNE,'top').card_id;g=self.game(hand=(cid,KILL),board=(UNIT,));eid=self.entity(g,cid)
        self.assertNotIn(UseHandAction(1,eid,'prepare'),g.legal_actions());self.play(g,cid)
        ally=g.state.players[1].board[0];self.assertEqual(g.state.entities[ally].attack,0);self.play(g,KILL,eid)
        self.assertEqual((g.state.entities[ally].attack,g.state.entities[ally].health),(1,21))

    def test_current_copy_keeps_prepared_new_face_discount_lock_and_distinct_attachment_identity(self):
        cid=AssembleRecipe(PREP,CURATOR,'bottom').card_id;g=self.game(hand=(cid,COPY_HAND));eid=self.entity(g,cid)
        self.use(g,eid,'prepare');self.play(g,COPY_HAND)
        ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid];self.assertEqual(len(ids),2)
        self.assertEqual(len({g.state.entities[i].preparation.cost_id for i in ids}),2)
        for i in ids:
            self.assertEqual(g.quote_cost(i).amount,0)
            with self.assertRaises(IllegalAction):g.apply(PlayCard(1,i))
        self.portable(g)

    def test_deck_round_trip_resets_prepare_and_discount_but_keeps_the_printed_new_operation(self):
        cid=AssembleRecipe(PREP,CURATOR,'bottom').card_id;g=self.game(hand=(cid,SHUFFLE),deck=());eid=self.entity(g,cid)
        self.use(g,eid,'prepare');self.play(g,SHUFFLE);self.assertIn(eid,g.state.players[1].hand)
        self.assertEqual(g.state.entities[eid].card_id,cid);self.assertIsNone(g.state.entities[eid].preparation)
        self.assertEqual(g.quote_cost(eid).amount,4);self.use(g,eid,'prepare');self.assertEqual(g.quote_cost(eid).amount,0)

    def test_play_and_bounce_reset_prepare_to_the_same_printed_new_face(self):
        cid=AssembleRecipe(PREP,CURATOR,'bottom').card_id;g=self.game(hand=(cid,BOUNCE));eid=self.entity(g,cid)
        self.use(g,eid,'prepare');self.next_turn(g);self.play(g,cid);self.play(g,BOUNCE,eid)
        self.assertIsNone(g.state.entities[eid].preparation);self.assertEqual(g.state.entities[eid].card_id,cid)
        self.assertEqual(g.quote_cost(eid).amount,4);self.assertIn(UseHandAction(1,eid,'prepare'),g.legal_actions())

    def test_trade_player_command_wait_restore_failure_and_private_draw_use_original_pipeline(self):
        cid=AssembleRecipe(TRADE,CURATOR,'bottom').card_id;g=self.game(hand=(cid,),board=(DRAW_WATCH,),mode='trade_wait')
        eid=self.entity(g,cid);port=g.for_player(1);view=port.observe()
        ref=view['observation']['players'][0]['hand'][0]['ref']
        result=port.submit({'revision':view['revision'],'action':{'type':'use_hand_action','card':ref,'action_id':'trade'}})
        self.assertTrue(result['accepted']);saved=self.portable(g);q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(q.player_id,q.id,('fault',)))
        self.assertEqual(g.snapshot(),saved);g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertIn(eid,g.state.players[1].deck);self.assertEqual(len(g.state.draw_history),1);self.portable(g)
        logs=g.player_events(2);started=next(x for x in logs if x['kind']=='trade_started')
        self.assertEqual(started['source']['card_id'],cid)
        self.assertIsNone(next(x for x in logs if x['kind']=='card_drawn')['target']['card_id'])

    def test_prepare_wait_restore_and_failed_resume_do_not_spend_investment_twice(self):
        cid=AssembleRecipe(PREP,CURATOR,'bottom').card_id;g=self.game(hand=(cid,),board=(PREP_WATCH,),mode='prepare_wait')
        eid=self.entity(g,cid);before=g.state.players[1].mana;self.use(g,eid,'prepare');saved=self.portable(g);q=g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError,'assembled Prepare observer fault'):g.apply(SelectChoice(q.player_id,q.id,('fault',)))
        self.assertEqual(g.snapshot(),saved);g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(g.state.players[1].mana,before-3);self.assertEqual(g.quote_cost(eid).amount,0);self.portable(g)

    def test_zero_mana_or_empty_trade_deck_rejects_without_state_event_or_rng_changes(self):
        for source,kind,mana,deck in((TRADE,'trade',0,DECK),(PREP,'prepare',0,DECK),(TRADE,'trade',30,())):
            with self.subTest(kind=kind,mana=mana,deck=bool(deck)):
                cid=AssembleRecipe(source,CURATOR,'bottom').card_id;g=self.game(hand=(cid,),mana=mana,deck=deck)
                eid=self.entity(g,cid);saved=g.snapshot()
                with self.assertRaises(IllegalAction):self.use(g,eid,kind)
                self.assertEqual(g.snapshot(),saved)

    def test_previous_core_version_is_rejected_and_player_views_do_not_export_declaration_receipts(self):
        cid=AssembleRecipe(PREP,CURATOR,'bottom').card_id;g=self.game(hand=(cid,));saved=g.snapshot()
        saved['mechanics_version']['version']='core-effects-v657'
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaisesRegex(SnapshotError,'(?i)mechanic'):Game.from_snapshot(saved,fixture(self.mode,'reader'))
        for pid in(1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for name in('definition_sha256','source_guard','source_sha256','prepared-01'):
                self.assertNotIn('"'+name+'"',visible)

    def test_complete_source_pins_are_checked_before_either_template_is_installed(self):
        r=build_registry()
        for cid in SOURCES:r._assemble_templates.pop(cid)
        r._cards[PREP]=replace(r.card(PREP),health=4)
        with self.assertRaisesRegex(TargetValidationError,'complete original source'):register_assemble_hand_action_prefix_fragments(r)
        self.assertTrue(all(cid not in r.assemble_templates for cid in SOURCES))


if __name__=='__main__':unittest.main()
