"""Exact Dream dependency bodies, Elusive and original-owner return."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
import json,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p17_cards import SISTER,DRAKE,DREAM,DEPENDENCIES,ROOTS,PARENT,load_batch,register_simple_followup_p17_cards
from hs_sim.engine import Attack,CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,PlayCard,PlayerSetup,Rarity,Scenario,SelectChoice,SpellSchool,TargetSpec,UseHeroPower,Zone
from hs_sim.engine.effects import Buff,ChangeControl,ChoiceOption,Damage,Freeze,GainArmor,GrantKeyword,InvokeBehavior,RequestChoice,Silence
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec,PLAYABLE_CARD_CLASSES
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest
TEST='p17.test.';YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def registry():
    r=build_registry();present=tuple(cid in r.cards for cid in DEPENDENCIES)
    if any(present)and not all(present):raise AssertionError('Partial P17 registration')
    if not all(present):register_simple_followup_p17_cards(r)
    def prep(c):return(Buff(c.target_id,3,3,c.source_id),Damage(c.target_id,1,c.source_id),Freeze(c.target_id),GrantKeyword(c.target_id,Keyword.LIFESTEAL,c.source_id))
    def auto(c):
        target=next(i for p in(1,2)for i in c.state.players[p].board if c.state.entities[i].card_id==SISTER)
        return(CastSpell(c.player_id,DREAM,c.source_id,target,targeting='explicit'),)
    for name,body in(('take',lambda c:(ChangeControl(c.target_id,1),)),('give',lambda c:(ChangeControl(c.target_id,2),)),
                      ('prep',prep),('silence',lambda c:(Silence(c.target_id),)),('auto',auto)):
        key=TEST+name;r.register_behavior(key,body)
        target=None if name=='auto'else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,targeting=target,metadata=META))
    r.register_behavior(TEST+'boost',lambda c:(Buff(c.target_id,1,1,c.source_id),))
    r.register_card(CardDefinition(TEST+'boost','Minion battlecry targeting',CardType.MINION,health=2,metadata=META,battlecry=TEST+'boost',targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    r.register_behavior(TEST+'silencer',lambda c:(Silence(c.target_id),))
    r.register_card(CardDefinition(TEST+'silencer','Minion battlecry silence',CardType.MINION,health=2,metadata=META,battlecry=TEST+'silencer',targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    r.register_behavior(TEST+'armor',lambda c:(GainArmor(c.state.players[c.player_id].hero_id,2),))
    r.register_card(CardDefinition(TEST+'rattle','Full-hand death witness',CardType.MINION,attack=1,health=3,metadata=META,deathrattle=TEST+'armor'))
    r.register_card(CardDefinition(TEST+'dormant','Dormant target',CardType.MINION,health=4,dormant_turns=2,metadata=META))
    r.register_card(CardDefinition(TEST+'stealth','Stealth target',CardType.MINION,health=4,keywords=(Keyword.STEALTH,),metadata=META))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P17 deliberate pending failure')))
    r.register_behavior(TEST+'wait',lambda c:(RequestChoice(c.player_id,(
        ChoiceOption('ok','Continue',()),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),)),
    ),c.source_id),))
    r.register_card(CardDefinition(TEST+'wait','Actual return reaction',CardType.MINION,health=8,metadata=META,limited_triggers=(LimitedTriggerSpec('card_returned',TEST+'wait'),)))
    r.validate();return r

class SimpleFollowupP17Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),*,enemy_hand=(),active=1):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),active_player=active,seed=1717),self.r)
    def first(self,g,cid,p=1,zone='board'):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        p=g.state.active_player;eid=self.first(g,cid,p,'hand').id;g.apply(PlayCard(p,eid,target,len(g.state.players[p].board)if self.r.card(cid).kind==CardType.MINION else None));return eid
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry());self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','CardReference','behavior_id','source_allocation'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_four_complete_raw_rows_eight_official_faces_and_full_dream_metadata(self):
        d=load_batch();rows=d['dependencies']+d['evidence_only'];self.assertEqual(len(rows),4);self.assertEqual(len(d['official_observations']['observations']),8)
        self.assertFalse(d['cards']);self.assertFalse(d['skipped']);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in rows:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            for o in(o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                f=o['face'];en=o['locale']=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']))
                self.assertEqual((f['id'],f['cardTypeId'],f['cardSetId']),(raw['dbf_id'],raw['tags']['CARDTYPE'],raw['card_set_id']))
                if raw['cost']is not None:self.assertEqual(f['manaCost'],raw['cost'])
            if raw['id']in DEPENDENCIES:
                meta=self.r.card(raw['id']).metadata;self.assertEqual(meta,replace(metadata_from_record(raw),deck_identity=raw['id']))
                self.assertEqual(meta.classes,(CardClass.DREAM,));self.assertFalse(meta.collectible);self.assertEqual(meta.rarity,Rarity.NONE)
        self.assertEqual(self.r.card(SISTER).metadata.tribes,());self.assertEqual(self.r.card(DRAKE).metadata.tribes,('dragon',))
        self.assertEqual(len(PLAYABLE_CARD_CLASSES),11);self.assertNotIn(CardClass.DREAM,PLAYABLE_CARD_CLASSES)

    def test_only_three_dependencies_added_no_collectible_root_or_partial_random_parent(self):
        # Isolate the original P17 increment: later complete parent recipes
        # intentionally reject a registry with one of their dependencies absent.
        with patch('hs_sim.cards.fixed_dream_source.register_fixed_dream_source',lambda r:None), patch('hs_sim.cards.simple_followup_p17_cards.register_simple_followup_p17_cards',lambda r:None):before=build_registry()
        with patch('hs_sim.cards.fixed_dream_source.register_fixed_dream_source',lambda r:None):after=build_registry()
        if not all(cid in after.cards for cid in DEPENDENCIES):register_simple_followup_p17_cards(after)
        self.assertFalse(ROOTS);self.assertEqual(set(after.cards)-set(before.cards),set(DEPENDENCIES));self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards))
        for cid in(PARENT,'DREAM_02','DREAM_05','VAN_DREAM_01','VAN_DREAM_03','VAN_DREAM_04'):self.assertEqual(cid in before.cards,cid in after.cards)
        for o in load_batch()['official_observations']['observations']:
            if o['card_id']==PARENT:self.assertEqual(sorted(o['face']['childIds']),[217,301,340,489,808])

    def test_default_311_and_fingerprint_remain(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_dream_missing_printed_cost_kept_none_execution_default_zero_and_nature(self):
        raw=next(x['record']for x in load_batch()['dependencies']if x['record']['id']==DREAM)
        self.assertIsNone(raw['cost']);self.assertNotIn('COST',raw['tags']);self.assertEqual(self.r.card(DREAM).cost,0);self.assertEqual(self.r.card(DREAM).spell_school,SpellSchool.NATURE)
        for o in load_batch()['official_observations']['observations']:
            if o['card_id']==DREAM:self.assertEqual(o['face']['manaCost'],0)
        g=self.game((DREAM,),enemy=(YETI,));target=self.first(g,YETI,2).id;self.play(g,DREAM,target);self.assertEqual(g.state.players[1].mana,40)
        self.assertEqual(g.state.play_history[-1].cost,0);self.assertEqual(g.state.entities[target].zone,Zone.HAND);self.portable(g)

    def test_sister_paid_native_elusive_body_and_drake_paid_vanilla_dragon(self):
        for cid,stats,paid in((SISTER,(3,5),2),(DRAKE,(7,6),4)):
            with self.subTest(cid=cid):
                g=self.game((cid,));source=self.play(g,cid);e=g.state.entities[source]
                self.assertEqual((e.attack,e.health),stats);self.assertEqual(g.state.players[1].mana,40-paid)
                self.assertEqual(Keyword.ELUSIVE in e.keywords,cid==SISTER);saved=g.snapshot()
                with self.assertRaises(IllegalAction):g.apply(Attack(1,source,g.state.players[2].hero_id))
                self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_sister_manual_spell_and_hero_power_protection_on_both_sides(self):
        for side in(1,2):
            with self.subTest(side=side):
                g=self.game((DREAM,),board=(SISTER,)if side==1 else(),enemy=(SISTER,)if side==2 else());target=self.first(g,SISTER,side).id;saved=g.snapshot()
                self.assertNotIn(target,g.legal_targets(self.first(g,DREAM,zone='hand').id))
                with self.assertRaises(IllegalAction):self.play(g,DREAM,target)
                self.assertEqual(g.snapshot(),saved)
                with self.assertRaises(IllegalAction):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,target))
                self.assertEqual(g.snapshot(),saved)

    def test_sister_allows_minion_battlecry_target_and_ordinary_combat(self):
        g=self.game((TEST+'boost',),(SISTER,));target=self.first(g,SISTER).id;self.play(g,TEST+'boost',target)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(4,6));self.portable(g)
        g=self.game(board=(SISTER,),enemy=(YETI,),active=2);target=self.first(g,SISTER).id
        g.apply(Attack(2,self.first(g,YETI,2).id,target));self.assertEqual(g.state.entities[target].health,1);self.portable(g)

    def test_sister_silence_removes_protection_before_owner_return(self):
        g=self.game((TEST+'silence',TEST+'silencer',DREAM),(SISTER,));target=self.first(g,SISTER).id
        self.assertNotIn(target,g.legal_targets(self.first(g,TEST+'silence',zone='hand').id))
        self.play(g,TEST+'silencer',target);self.assertNotIn(Keyword.ELUSIVE,g.state.entities[target].keywords);self.play(g,DREAM,target)
        self.assertIn(target,g.state.players[1].hand);self.assertIn(Keyword.ELUSIVE,g.state.entities[target].keywords);self.portable(g)

    def test_native_automatic_dream_can_use_existing_elusive_bypass_policy(self):
        g=self.game((TEST+'auto',),enemy=(SISTER,));target=self.first(g,SISTER,2).id;self.play(g,TEST+'auto')
        self.assertEqual(g.state.entities[target].zone,Zone.HAND);self.assertEqual(g.state.entities[target].controller,2)
        self.assertEqual([c.card_id for c in g.state.cast_history],[TEST+'auto',DREAM]);self.portable(g)

    def test_dream_both_sides_return_same_physical_body_to_original_owner(self):
        for side in(1,2):
            with self.subTest(side=side):
                g=self.game((DREAM,),board=(DRAKE,)if side==1 else(),enemy=(DRAKE,)if side==2 else());target=self.first(g,DRAKE,side).id
                self.play(g,DREAM,target);self.assertIn(target,g.state.players[side].hand);self.assertEqual((g.state.entities[target].owner,g.state.entities[target].controller),(side,side))
                self.assertFalse(g.state.death_history);self.portable(g)

    def test_dream_borrowed_enemy_body_returns_to_other_owner_hand(self):
        g=self.game((TEST+'take',DREAM),enemy=(DRAKE,));target=self.first(g,DRAKE,2).id;self.play(g,TEST+'take',target);self.assertIn(target,g.state.players[1].board)
        self.play(g,DREAM,target);self.assertIn(target,g.state.players[2].hand);self.assertNotIn(target,g.state.players[1].hand)
        self.assertEqual((g.state.entities[target].owner,g.state.entities[target].controller),(2,2));self.portable(g)

    def test_dream_own_body_given_away_still_returns_to_owner(self):
        g=self.game((TEST+'give',DREAM),(DRAKE,));target=self.first(g,DRAKE).id;self.play(g,TEST+'give',target);self.play(g,DREAM,target)
        self.assertIn(target,g.state.players[1].hand);self.assertEqual((g.state.entities[target].owner,g.state.entities[target].controller),(1,1))

    def test_dream_successful_return_resets_old_local_stats_injury_keywords_and_freeze(self):
        g=self.game((TEST+'prep',DREAM),(TEST+'rattle',));target=self.first(g,TEST+'rattle').id;self.play(g,TEST+'prep',target);self.play(g,DREAM,target);e=g.state.entities[target]
        self.assertEqual((e.attack,e.health,e.max_health),(1,3,3));self.assertFalse(e.frozen);self.assertNotIn(Keyword.LIFESTEAL,e.keywords)
        self.assertFalse(g.state.death_history);self.assertFalse(g.state.deathrattle_history);self.portable(g)

    def test_dream_full_owner_hand_destroys_under_current_controller_without_reset_or_success(self):
        g=self.game((TEST+'take',TEST+'prep',DREAM),enemy=(TEST+'rattle',),enemy_hand=(YETI,)*10);target=self.first(g,TEST+'rattle',2).id
        self.play(g,TEST+'take',target);self.play(g,TEST+'prep',target);self.play(g,DREAM,target);death,=g.state.death_history
        self.assertEqual((death.owner,death.controller,death.attack,death.max_health,death.damage),(2,1,4,6,1))
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        self.assertFalse(any(e.kind=='card_returned'for e in g.events));self.assertTrue(any(e.kind=='card_burned'for e in g.events));self.assertTrue(g.state.deathrattle_history[-1].completed);self.portable(g)

    def test_dream_required_board_minion_target_rejects_hero_hand_deck_dormant_and_enemy_stealth(self):
        g=self.game((DREAM,DRAKE),board=(TEST+'dormant',),enemy=(TEST+'stealth',));source=self.first(g,DREAM,zone='hand').id
        invalid=(None,g.state.players[1].hero_id,g.state.players[2].hero_id,self.first(g,DRAKE,zone='hand').id,g.state.players[1].deck[0],g.state.players[1].board[0],g.state.players[2].board[0])
        for target in invalid:
            saved=g.snapshot()
            with self.assertRaises(IllegalAction):g.apply(PlayCard(1,source,target))
            self.assertEqual(g.snapshot(),saved)

    def test_dream_wait_after_actual_return_restores_once_and_bad_choice_rolls_back(self):
        g=self.game((DREAM,),(TEST+'wait',),enemy=(DRAKE,));target=self.first(g,DRAKE,2).id;self.play(g,DREAM,target)
        self.assertIn(target,g.state.players[2].hand);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(sum(e.kind=='card_returned'for e in g.events),1);self.assertEqual(g.state.players[1].mana,40);self.portable(g)

if __name__=='__main__':unittest.main()
