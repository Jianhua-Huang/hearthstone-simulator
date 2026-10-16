"""Original shared current-type buff inventory and retained blocked source pins."""
from dataclasses import replace
import json,re,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p12_cards import ENTROPY,TREES,FLEET,SHRED,TREANT,ROOTS,SKIPPED,load_batch,register_simple_followup_p12_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,ChangeMinionTribes,EndTurn,Game,IllegalAction,PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,TribeChangeSpec,Zone
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import ChangeControl,ChoiceOption,Destroy,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest
TEST='p12.test.';YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def registry():
    r=build_registry()
    if FLEET not in r.cards:register_simple_followup_p12_cards(r)
    for name,tribes in(('beast',('beast',)),('dragon',('dragon',)),('dual',('beast','dragon')),('all',('all',)),('empty',()),('future',('future.type',))):
        r.register_card(CardDefinition(TEST+name,name,CardType.MINION,attack=2,health=5,metadata=replace(META,tribes=tribes)))
    r.register_card(CardDefinition(TEST+'unknown','Unknown',CardType.MINION,attack=2,health=5))
    r.register_card(CardDefinition(TEST+'dormant','Dormant',CardType.MINION,attack=2,health=5,dormant_turns=2,metadata=replace(META,tribes=('beast',))))
    def change(c,operation,tribes):return(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec(operation,tribes),c.source_id),)
    for name,body in(
        ('to_beast',lambda c:change(c,'set',('beast',))),('to_dragon',lambda c:change(c,'set',('dragon',))),
        ('exclude_beast',lambda c:change(c,'remove',('beast',))),('empty_type',lambda c:change(c,'set',())),
        ('silence',lambda c:(Silence(c.target_id),))):
        key=TEST+name;r.register_behavior(key,body);r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    def reenter(c):
        e=c.state.entities[c.target_id]
        return(SummonStoredCard(CardReference.capture(e),e.controller,cause=SummonCause.capture(c)),)
    r.register_behavior(TEST+'reenter',reenter)
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P12 deliberate late choice failure')))
    def wait(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=FLEET:return ()
        other=next(i for i in c.state.players[1].board if i!=c.event.target_id and c.state.entities[i].card_id==TEST+'beast')
        ref=MinionReference.capture(c.state.entities[other])
        return(RequestChoice(1,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),)),
            ChoiceOption('new','New matching body',(SummonByCard(1,(SummonEntryMaterial(TEST+'beast'),),SummonCause.capture(c)),)),
            ChoiceOption('bounce','Same ID new residence',(ReturnToHand(other),InvokeBehavior(TEST+'reenter',c.source_id,1,other))),
            ChoiceOption('form','New face',(Transform(other,TEST+'dragon'),)),
            ChoiceOption('control','Different controller',(ChangeControl(other,2),)),
            ChoiceOption('kill','Retired body',(Destroy(other,c.source_id),)),
            ChoiceOption('type','Original body different tribe',(ChangeMinionTribes(ref,TribeChangeSpec('set',('dragon',)),c.source_id),)),
        ),c.source_id),)
    r.register_behavior(TEST+'wait',wait)
    r.register_card(CardDefinition(TEST+'wait','One buff observer',CardType.MINION,health=9,metadata=META,limited_triggers=(LimitedTriggerSpec('stats_changed',TEST+'wait'),)))
    r.validate();return r

class SimpleFollowupP12Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(FLEET,),board=(),enemy=(),*,enemy_hand=(),active=1):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),active_player=active,seed=1212),self.r)
    def entities(self,g,cid,p=1,zone='board'):return[g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def play(self,g,cid=FLEET,target=None):
        p=g.state.active_player;source=self.first(g,cid,p,'hand').id;g.apply(PlayCard(p,source,target));return source
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def stats(self,g,eid):
        e=g.state.entities[eid];return(e.attack,e.max_health)
    def fleet(self,g,cid=TEST+'beast'):return self.play(g,target=self.first(g,cid).id)
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry());self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        for p in(1,2):
            dto=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','MinionReference','zone_epoch','behavior_id','summon_attack_profiles'):
                self.assertNotIn('"'+key+'"',dto)
        return other

    def test_all_five_complete_raw_pins_ten_full_official_faces_and_metadata(self):
        d=load_batch();rows=d['cards']+d['skipped']+d['evidence_only'];self.assertEqual({x['record']['id']for x in rows},{FLEET,ENTROPY,TREES,SHRED,TREANT})
        self.assertEqual(len(d['official_observations']['observations']),10);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in rows:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            for o in(o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                f=o['face'];en=o['locale']=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']))
                self.assertEqual((f['id'],f['cardTypeId'],f['cardSetId']),(raw['dbf_id'],raw['tags']['CARDTYPE'],raw['card_set_id']))
                if raw['cost']is not None:self.assertEqual(f['manaCost'],raw['cost'])
        raw=d['cards'][0]['record'];self.assertEqual(self.r.card(FLEET).metadata,replace(metadata_from_record(raw),deck_identity=FLEET));self.assertIsNone(self.r.card(FLEET).spell_school)
        shred=next(x['record']for x in rows if x['record']['id']==SHRED);self.assertIsNone(shred['cost']);self.assertNotIn('COST',shred['tags']);self.assertNotIn('SPELL_SCHOOL',shred['tags']);self.assertEqual(shred['tags']['349'],1)

    def test_skipped_whole_roots_and_their_exact_children_remain_unregistered(self):
        self.assertEqual(ROOTS,(FLEET,));self.assertEqual(SKIPPED,(ENTROPY,TREES));d=load_batch()
        for cid in(*SKIPPED,SHRED,TREANT):self.assertNotIn(cid,self.r.cards)
        for o in d['official_observations']['observations']:
            if o['card_id']in SKIPPED:self.assertEqual(o['face']['childIds'],[120483 if o['card_id']==ENTROPY else 118492])

    def test_default_311_and_fingerprint_remain(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')

    def test_paid_primary_and_same_type_get_one_plus_one_two_enemy_and_other_type_unchanged(self):
        g=self.game(board=(TEST+'beast',TEST+'beast',TEST+'dragon'),enemy=(TEST+'beast',));old=g.state.players[1].board;enemy=g.state.players[2].board[0];rng=g._rng.getstate()
        self.fleet(g);self.assertEqual([self.stats(g,i)for i in old],[(3,7),(3,7),(2,5)]);self.assertEqual(self.stats(g,enemy),(2,5))
        self.assertEqual(g.state.players[1].mana,37);self.assertEqual(len(g.state.cast_history),1);self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_untyped_primary_always_buffs_itself_and_no_other_untyped_or_all(self):
        g=self.game(board=(TEST+'empty',TEST+'empty',TEST+'all',TEST+'unknown'));ids=g.state.players[1].board;self.fleet(g,TEST+'empty')
        self.assertEqual([self.stats(g,i)for i in ids],[(3,7),(2,5),(2,5),(2,5)]);self.portable(g)

    def test_dual_and_all_are_each_one_physical_recipient(self):
        g=self.game(board=(TEST+'dual',TEST+'beast',TEST+'dragon',TEST+'all',TEST+'dual',TEST+'empty'));ids=g.state.players[1].board;self.fleet(g,TEST+'dual')
        self.assertEqual([self.stats(g,i)for i in ids],[(3,7)]*5+[(2,5)]);self.assertEqual(sum(e.kind=='stats_changed'for e in g.events),5);self.portable(g)

    def test_all_primary_includes_future_type_and_other_all_but_not_untyped(self):
        g=self.game(board=(TEST+'all',TEST+'future',TEST+'all',TEST+'empty'));ids=g.state.players[1].board;self.fleet(g,TEST+'all')
        self.assertEqual([self.stats(g,i)for i in ids],[(3,7)]*3+[(2,5)]);self.portable(g)

    def test_current_all_exclusion_is_respected_in_both_operand_positions(self):
        for primary in(TEST+'all',TEST+'beast'):
            with self.subTest(primary=primary):
                g=self.game((TEST+'exclude_beast',FLEET),(TEST+'all',TEST+'beast',TEST+'dragon'))
                ids=g.state.players[1].board;self.play(g,TEST+'exclude_beast',ids[0]);self.fleet(g,primary)
                self.assertEqual([self.stats(g,i)for i in ids],[(3,7),(2,5),(3,7)]if primary==TEST+'all'else[(2,5),(3,7),(2,5)])

    def test_current_granted_type_qualifies_and_removed_printed_type_does_not(self):
        g=self.game((TEST+'to_beast',TEST+'empty_type',FLEET),(TEST+'beast',TEST+'dragon',TEST+'beast'))
        a,b,c=g.state.players[1].board;self.play(g,TEST+'to_beast',b);self.play(g,TEST+'empty_type',c);self.fleet(g)
        self.assertEqual([self.stats(g,i)for i in(a,b,c)],[(3,7),(3,7),(2,5)]);self.portable(g)

    def test_silence_restores_printed_type_before_actual_match(self):
        g=self.game((TEST+'to_dragon',TEST+'silence',FLEET),(TEST+'beast',TEST+'beast'));a,b=g.state.players[1].board
        self.play(g,TEST+'to_dragon',b);self.play(g,TEST+'silence',b);self.fleet(g);self.assertEqual([self.stats(g,i)for i in(a,b)],[(3,7)]*2)

    def test_dormant_matching_other_is_not_in_original_live_inventory(self):
        g=self.game(board=(TEST+'beast',TEST+'dormant'));a,b=g.state.players[1].board;self.fleet(g)
        self.assertEqual([self.stats(g,i)for i in(a,b)],[(3,7),(2,5)]);self.portable(g)

    def test_unknown_primary_or_relevant_candidate_fails_entire_paid_action(self):
        for primary in(TEST+'unknown',TEST+'beast'):
            with self.subTest(primary=primary):
                g=self.game(board=(TEST+'beast',TEST+'unknown'));saved=g.snapshot()
                with self.assertRaisesRegex(ResolutionError,'tribe is unknown'):self.fleet(g,primary)
                self.assertEqual(g.snapshot(),saved)

    def test_native_required_target_legality_rejects_hero_enemy_dormant_and_missing(self):
        g=self.game(board=(TEST+'beast',TEST+'dormant'),enemy=(TEST+'beast',));target=self.first(g,FLEET,zone='hand').id
        for bad in(None,g.state.players[1].hero_id,g.state.players[2].board[0],self.first(g,TEST+'dormant').id):
            saved=g.snapshot()
            with self.assertRaises(IllegalAction):g.apply(PlayCard(1,target,bad))
            self.assertEqual(g.snapshot(),saved)
        self.assertIsInstance(g.for_player(1).legal_actions(),dict);self.fleet(g)

    def test_countered_spell_keeps_payment_and_does_not_buff(self):
        g=self.game(board=(TEST+'beast',),enemy_hand=('CORE_EX1_287',),active=2);self.play(g,'CORE_EX1_287');g.apply(EndTurn(2));target=self.first(g,TEST+'beast').id
        before=g.state.players[1].mana;self.fleet(g);self.assertEqual(self.stats(g,target),(2,5));self.assertEqual(g.state.players[1].mana,before-3);self.assertTrue(g.state.play_history[-1].countered);self.portable(g)

    def test_first_primary_buff_wait_preserves_original_inventory_and_failed_choice_rolls_back(self):
        g=self.game(board=(TEST+'beast',TEST+'wait',TEST+'beast'));a,_,b=g.state.players[1].board;self.fleet(g)
        self.assertEqual([self.stats(g,i)for i in(a,b)],[(3,7),(2,5)]);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.stats(g,b),(3,7));self.portable(g)

    def test_primary_is_first_recipient_even_when_later_in_board_order(self):
        g=self.game(board=(TEST+'beast',TEST+'wait',TEST+'beast'));a,_,b=g.state.players[1].board;self.play(g,target=b)
        self.assertEqual([self.stats(g,i)for i in(a,b)],[(2,5),(3,7)]);self.choose(g);self.assertEqual(self.stats(g,a),(3,7))

    def test_new_matching_minion_after_acceptance_does_not_join_original_plan(self):
        g=self.game(board=(TEST+'beast',TEST+'wait',TEST+'beast'));self.fleet(g);self.choose(g,'new')
        self.assertEqual([(e.attack,e.max_health)for e in self.entities(g,TEST+'beast')],[(3,7),(3,7),(2,5)]);self.portable(g)

    def test_captured_recipient_never_rebinds_reentry_transform_control_or_dead_body(self):
        for key in('bounce','form','control','kill'):
            with self.subTest(key=key):
                g=self.game(board=(TEST+'beast',TEST+'wait',TEST+'beast'));source=g.state.players[1].board[-1];self.fleet(g);self.choose(g,key)
                self.assertEqual(self.stats(g,source),(2,5));self.portable(g)

    def test_later_type_change_does_not_rewrite_already_captured_recipient(self):
        g=self.game(board=(TEST+'beast',TEST+'wait',TEST+'beast'));source=g.state.players[1].board[-1];self.fleet(g);other=self.portable(g)
        self.choose(g,'type');self.choose(other,'type');self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.stats(g,source),(3,7));self.portable(g)

if __name__=='__main__':unittest.main()
