"""Native weapon death draws, fixed chosen companions and retained attack gap."""
from dataclasses import asdict,replace
import json,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p13_cards import SABRE,SHOVEL,SPEAKER,ROOTS,COMPANIONS,load_batch,register_simple_followup_p13_cards
from hs_sim.engine import Attack,CardClass,CardDefinition,CardMetadata,CardType,DeckPolicy,DeckSpec,Game,Keyword,MatchSetup,OpeningHook,PlayCard,PlayerSetup,Rarity,Scenario,SelectChoice,Zone
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import AddToHand,ChangeManaCrystals,ChoiceOption,Destroy,EquipWeapon,InvokeBehavior,ModifyWeapon,RequestChoice
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import AddToDeck,CardReference,CopyCard,MoveCard
from hs_sim.targets import canonical_digest
TEST='p13.test.';PLAIN=TEST+'plain';BOOT=TEST+'boot';SETUP=TEST+'setup';REPLACE=TEST+'replace';YETI='CORE_CS2_182'
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())

def registry():
    r=build_registry();present=tuple(cid in r.cards for cid in ROOTS)
    if any(present)and not all(present):raise AssertionError('Partial P13 registration')
    if not all(present):register_simple_followup_p13_cards(r)
    def boot(c):
        return (ChangeManaCrystals(1,10,filled=True),*(AddToHand(1,cid,c.source_id)for cid in(SHOVEL,REPLACE,SETUP)))if c.player_id==1 else ()
    r.register_behavior(TEST+'boot',boot)
    r.register_card(CardDefinition(BOOT,'Opening fixture',CardType.MINION,health=1,metadata=META,opening_hooks=(OpeningHook('after_mulligan',TEST+'boot'),)))
    r.register_behavior(TEST+'noop',lambda c:())
    r.register_card(CardDefinition(PLAIN,'Same face original/generated spell',CardType.SPELL,on_play=TEST+'noop',metadata=META))
    r.register_card(CardDefinition(TEST+'weapon','Replacement',CardType.WEAPON,attack=1,durability=2,metadata=META))
    r.register_behavior(TEST+'replace',lambda c:(EquipWeapon(c.player_id,TEST+'weapon'),))
    r.register_card(CardDefinition(REPLACE,'Replace weapon',CardType.SPELL,on_play=TEST+'replace',metadata=META))
    def original(c,p):
        ids=set(c.state.opening.original_entities[p-1])
        return next(c.state.entities[i]for i in c.state.players[p].deck if i in ids and c.state.entities[i].card_id==PLAIN)
    def setup(c):
        own=CardReference.capture(original(c,1));foreign=CardReference.capture(original(c,2));weapon=c.state.players[1].weapon_id
        add=AddToDeck(1,PLAIN,'bottom',c.source_id);chip=ModifyWeapon(weapon,durability=-1,source_id=c.source_id)
        return(RequestChoice(1,(
            ChoiceOption('generated','Same face new allocation',(add,)),
            ChoiceOption('copy','New original-face copy',(CopyCard(own,1,Zone.DECK,mode='base',position='bottom',source_id=c.source_id),)),
            ChoiceOption('transformed','Original physical same-face replacement',(TransformStoredCard(own,PLAIN,c.source_id),)),
            ChoiceOption('foreign','Other deck original',(MoveCard(foreign,1,Zone.DECK,source_id=c.source_id),)),
            ChoiceOption('minion','Outside minion only',(AddToDeck(1,YETI,'bottom',c.source_id),)),
            ChoiceOption('many','Three distinct outside spells',(add,add,add)),
            ChoiceOption('last','Outside spell and last durability',(add,chip)),
            ChoiceOption('burn','Full hand and last durability',(add,chip,*(AddToHand(1,YETI,c.source_id)for _ in range(10)))),
            ChoiceOption('drawcast','Outside Casts When Drawn',(AddToDeck(1,'JAIL_443t','bottom',c.source_id),)),
            ChoiceOption('wait','Actual draw reaction',(add,SummonByCard(1,(SummonEntryMaterial(TEST+'draw_wait'),),SummonCause.capture(c)))),
        ),c.source_id),)
    r.register_behavior(TEST+'setup',setup);r.register_card(CardDefinition(SETUP,'Prepare physical candidates',CardType.SPELL,on_play=TEST+'setup',metadata=META))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P13 deliberate late failure')))
    def wait(c):
        source=c.state.entities.get(c.event.source_id)
        if c.event.kind=='card_drawn':
            if source is None or source.card_id!=SHOVEL:return ()
        elif c.state.entities[c.event.target_id].card_id not in COMPANIONS:return ()
        original=next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==SPEAKER),c.event.source_id)
        return(RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),)),
            ChoiceOption('kill','Remove original source',(Destroy(original,c.source_id),)),
        ),c.source_id),)
    r.register_behavior(TEST+'wait',wait)
    r.register_trigger_condition(TEST+'actual_wait',lambda c:
        c.state.entities[c.event.source_id].card_id==SHOVEL if c.event.kind=='card_drawn'
        else c.state.entities[c.event.target_id].card_id in COMPANIONS)
    for name,event in(('draw_wait','card_drawn'),('summon_wait','minion_summoned')):
        r.register_card(CardDefinition(TEST+name,name,CardType.MINION,health=8,metadata=META,limited_triggers=(LimitedTriggerSpec(event,TEST+'wait',condition_id=TEST+'actual_wait'),)))
    r.validate();return r

class SimpleFollowupP13Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=()):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),seed=1313),self.r)
    def match(self):
        cards=(BOOT,)+(PLAIN,)*11;policy=DeckPolicy('p13.original','p13.actual-opening-fixture','experimental',(BOOT,PLAIN),deck_size=12,max_copies=12)
        g=Game.from_decks(MatchSetup(tuple(DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,cards)for _ in(1,2)),policy,'GAME_005',seed=1313,first_player=1),self.r)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        return g
    def entities(self,g,cid,p=1,zone='board'):return[g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def play(self,g,cid,target=None):
        p=g.state.active_player;source=self.first(g,cid,p,'hand').id;g.apply(PlayCard(p,source,target,len(g.state.players[p].board)if self.r.card(cid).kind==CardType.MINION else None));return source
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def prepare(self,g,key):self.play(g,SETUP);self.choose(g,key)
    def rows(self,g,source):return[d for d in g.state.draw_history if d.source_id==source and d.parent_id is None]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry());self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','CardReference','original_entities','behavior_id','hand_cursor'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_six_full_raw_rows_twelve_official_faces_and_complete_new_metadata(self):
        d=load_batch();rows=d['cards']+d['skipped']+d['existing_dependencies'];self.assertEqual(len(rows),6);self.assertEqual(len(d['official_observations']['observations']),12)
        self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in rows:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            for o in(o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                f=o['face'];en=o['locale']=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']))
                self.assertEqual((f['id'],f['manaCost'],f['cardTypeId'],f['cardSetId']),(raw['dbf_id'],raw['cost'],raw['tags']['CARDTYPE'],raw['card_set_id']))
            if raw['id']!=SABRE:self.assertEqual(self.r.card(raw['id']).metadata,replace(metadata_from_record(raw),deck_identity=raw['id']))
        for o in d['official_observations']['observations']:
            if o['card_id']==SPEAKER:self.assertEqual(sorted(o['face']['childIds']),[100,226,959])

    def test_all_existing_companion_definitions_are_retained_without_re_registration(self):
        with patch('hs_sim.cards.simple_followup_p13_cards.register_simple_followup_p13_cards',lambda r:None):
            before=build_registry()
        after=build_registry()
        if not all(cid in after.cards for cid in ROOTS):register_simple_followup_p13_cards(after)
        for cid in COMPANIONS:self.assertEqual(asdict(before.card(cid)),asdict(after.card(cid)))
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertNotIn(SABRE,after.cards)

    def test_default_311_and_complete_fingerprint_remain(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')

    def test_shovel_printed_weapon_payment_no_draw_until_actual_death(self):
        g=self.match();source=self.play(g,SHOVEL);e=g.state.entities[source]
        self.assertEqual((e.attack,e.durability),(1,2));self.assertFalse(self.rows(g,source));self.assertEqual(g.state.players[1].weapon_id,source);self.portable(g)

    def test_shovel_scenario_without_original_opening_fails_and_rolls_back_replacement(self):
        g=self.game((SHOVEL,REPLACE));self.play(g,SHOVEL);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,REPLACE)
        self.assertEqual(g.snapshot(),saved)

    def test_shovel_unchanged_original_spells_all_excluded_without_rng_or_fatigue(self):
        g=self.match();source=self.play(g,SHOVEL);rng=g._rng.getstate();self.play(g,REPLACE)
        self.assertFalse(self.rows(g,source));self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].fatigue,0);self.portable(g)

    def test_shovel_generated_same_name_is_selected_over_original_physical_cards(self):
        g=self.match();source=self.play(g,SHOVEL);self.prepare(g,'generated');original=set(g.state.opening.original_entities[0]);self.play(g,REPLACE)
        row,=self.rows(g,source);self.assertEqual(row.card_id,PLAIN);self.assertNotIn(row.entity_id,original);self.assertEqual(row.outcome,'hand')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)

    def test_shovel_new_copy_same_face_replacement_and_foreign_original_are_outside(self):
        for key in('copy','transformed','foreign'):
            with self.subTest(key=key):
                g=self.match();source=self.play(g,SHOVEL);self.prepare(g,key);self.play(g,REPLACE);row,=self.rows(g,source);e=g.state.entities[row.entity_id]
                self.assertEqual(row.card_id,PLAIN)
                if key=='transformed':self.assertIn(e.id,g.state.opening.original_entities[0]);self.assertTrue(e.face_replaced)
                elif key=='foreign':self.assertIn(e.id,g.state.opening.original_entities[1]);self.assertEqual(e.owner,2);self.assertEqual(e.controller,1)
                else:self.assertNotIn(e.id,g.state.opening.original_entities[0]);self.assertIsNotNone(e.origin_entity_id)
                self.portable(g)

    def test_shovel_outside_minion_is_not_a_spell_tutor_candidate(self):
        g=self.match();source=self.play(g,SHOVEL);self.prepare(g,'minion');rng=g._rng.getstate();self.play(g,REPLACE)
        self.assertFalse(self.rows(g,source));self.assertEqual(g._rng.getstate(),rng);self.assertTrue(self.entities(g,YETI,zone='deck'))

    def test_shovel_last_durability_real_hero_attack_triggers_original_weapon_death(self):
        g=self.match();source=self.play(g,SHOVEL);self.prepare(g,'last');g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(len(self.rows(g,source)),1);self.portable(g)

    def test_shovel_full_hand_uses_actual_tutor_burn_not_discard_or_fatigue(self):
        g=self.match();source=self.play(g,SHOVEL);self.prepare(g,'burn');self.assertEqual(len(g.state.players[1].hand),10)
        g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id));row,=self.rows(g,source)
        self.assertEqual(row.outcome,'burned');self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(g.state.players[1].fatigue,0);self.portable(g)

    def test_shovel_draw_cast_uses_native_spell_body_and_unfiltered_replacement_chain(self):
        g=self.match();source=self.play(g,SHOVEL);self.prepare(g,'drawcast');self.play(g,REPLACE);row,=self.rows(g,source)
        self.assertEqual(row.card_id,'JAIL_443t');self.assertIsNotNone(row.cast_id);self.assertIsNotNone(row.replacement_id)
        leaf=g.state.draw_history[row.replacement_id-1];self.assertEqual(leaf.card_id,PLAIN);self.assertIn(leaf.entity_id,g.state.opening.original_entities[0]);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28);self.portable(g)

    def test_shovel_three_same_name_physical_candidates_draw_only_one(self):
        g=self.match();source=self.play(g,SHOVEL);self.prepare(g,'many');outside={i for i in g.state.players[1].deck if i not in g.state.opening.original_entities[0]}
        self.assertEqual(len(outside),3);self.play(g,REPLACE);row,=self.rows(g,source);self.assertIn(row.entity_id,outside);self.assertEqual(len(outside.intersection(g.state.players[1].deck)),2)

    def test_shovel_actual_draw_wait_restores_and_failed_choice_retains_original_death_and_draw(self):
        g=self.match();source=self.play(g,SHOVEL);self.prepare(g,'wait');self.play(g,REPLACE);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.rows(g,source)),1);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'ok');self.choose(other,'ok');self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.rows(g,source)),1);self.portable(g)

    def test_speaker_native_battlecry_pays_once_and_offers_three_exact_ordinary_choices_without_rng(self):
        g=self.game((SPEAKER,));rng=g._rng.getstate();source=self.play(g,SPEAKER);q=g.state.pending_choice
        self.assertEqual(tuple(o.id for o in q.options),COMPANIONS);self.assertEqual(tuple(o.card_id for o in q.options),COMPANIONS)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health,g.state.players[1].mana),(2,2,36));self.assertEqual(g._rng.getstate(),rng)
        self.portable(g);self.choose(g,'NEW1_032');self.assertEqual(g._rng.getstate(),rng)

    def test_speaker_each_exact_selected_companion_has_complete_native_effect(self):
        for cid in COMPANIONS:
            with self.subTest(cid=cid):
                g=self.game((SPEAKER,));source=self.play(g,SPEAKER);self.choose(g,cid);e=self.first(g,cid)
                self.assertEqual((e.attack,e.health),{'NEW1_034':(4,2),'NEW1_033':(2,4),'NEW1_032':(4,4)}[cid])
                self.assertEqual(sum(len(self.entities(g,other))for other in COMPANIONS),1)
                if cid=='NEW1_034':self.assertIn(Keyword.CHARGE,e.keywords);g.apply(Attack(1,e.id,g.state.players[2].hero_id))
                elif cid=='NEW1_032':self.assertIn(Keyword.TAUNT,e.keywords)
                else:self.assertEqual(g.state.entities[source].attack,3)
                self.portable(g)

    def test_speaker_choice_is_private_and_invalid_or_foreign_submission_rolls_back(self):
        g=self.game((SPEAKER,));self.play(g,SPEAKER);saved=g.snapshot();q=g.state.pending_choice
        for pid,key in((1,'not-a-companion'),(2,COMPANIONS[0])):
            with self.assertRaises((IllegalAction,ResolutionError)):g.apply(SelectChoice(pid,q.id,(key,)))
            self.assertEqual(g.snapshot(),saved)
        visible=json.dumps(g.for_player(2).observe())+json.dumps(g.for_player(2).legal_actions())
        for cid in COMPANIONS:self.assertNotIn(cid,visible)
        other=self.portable(g);self.choose(g,COMPANIONS[0]);self.choose(other,COMPANIONS[0]);self.assertEqual(g.snapshot(),other.snapshot())

    def test_speaker_full_board_after_own_entry_keeps_actual_failed_summon(self):
        g=self.game((SPEAKER,),(YETI,)*6);source=self.play(g,SPEAKER);self.choose(g,COMPANIONS[0])
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertFalse(self.entities(g,COMPANIONS[0]));self.assertEqual(len(g.state.card_summon_history),1);self.portable(g)

    def test_speaker_quantity_extra_keeps_exact_chosen_companion(self):
        g=self.game((SPEAKER,),('CORE_DAL_575',));self.play(g,SPEAKER);self.choose(g,'NEW1_032')
        self.assertEqual(len(self.entities(g,'NEW1_032')),2);self.assertFalse(self.entities(g,'NEW1_033'));self.portable(g)

    def test_speaker_repeated_actual_battlecry_has_two_independent_choices(self):
        g=self.game((SPEAKER,),('TIME_064',));self.play(g,SPEAKER);self.choose(g,'NEW1_032');self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g);self.choose(g,'NEW1_033');self.choose(other,'NEW1_033');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual((len(self.entities(g,'NEW1_032')),len(self.entities(g,'NEW1_033'))),(1,1));self.assertEqual(g.state.players[1].mana,36);self.portable(g)

    def test_speaker_actual_selected_summon_wait_recovers_without_reselecting_or_repaying(self):
        g=self.game((SPEAKER,),(TEST+'summon_wait',));source=self.play(g,SPEAKER);self.choose(g,'NEW1_034')
        self.assertEqual(len(self.entities(g,'NEW1_034')),1);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'kill');self.choose(other,'kill');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(self.entities(g,'NEW1_034')),1);self.assertEqual(g.state.players[1].mana,36);self.portable(g)

if __name__=='__main__':unittest.main()
