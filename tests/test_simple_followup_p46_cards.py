"""Current physical-deck threshold and original Shaku attack-declaration Get."""
from dataclasses import asdict,replace
from functools import lru_cache
import json,random,re,unittest
from unittest.mock import patch
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p46_cards import DEFENDER,SHAKU,LEGACY,ROOTS,RELATION,QUERY,POOL_ID,load_batch,register_simple_followup_p46_cards
from hs_sim.engine import Attack,CardClass,CardDefinition,CardMetadata,CardType,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,Zone
from hs_sim.engine.effects import AddToHand,Buff,ChangeControl,ChoiceOption,Draw,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import canonical_digest

TEST='p46.test.';YETI='CORE_CS2_182';OWN='EX1_124';DUAL='END_031';SPELL='CORE_BT_491';MINION='TID_700';WEAPON='CS2_106';MAGE='CORE_CS2_029'
MEMBERS=(SHAKU,YETI,OWN,DUAL,SPELL,MINION,WEAPON,MAGE);CONTEXT=GenerationContext('p46-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    present=tuple(cid in r.cards for cid in ROOTS)
    if not any(present):register_simple_followup_p46_cards(r)
    elif not all(present):raise AssertionError('P46 central batch must be complete')
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p46-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    scripts={'draw':lambda c:(Draw(1,source_id=c.source_id),),'add':lambda c:(AddToDeck(1,YETI,'top',c.source_id),),'enemy_add':lambda c:(AddToDeck(2,YETI,'top',c.source_id),),'draw_burn':lambda c:(AddToHand(1,YETI,c.source_id),Draw(1,source_id=c.source_id)),'buff':lambda c:(Buff(c.target_id,3,source_id=c.source_id),),'silence':lambda c:(Silence(c.target_id),),'give':lambda c:(ChangeControl(c.target_id,2),),'hero_attack':lambda c:(Buff(c.state.players[1].hero_id,2,source_id=c.source_id,expires_turn=c.state.turn),),'natural':lambda c:(Summon(1,DEFENDER),Summon(1,SHAKU)),'fail':lambda c:(_ for _ in()).throw(ResolutionError('P46 deliberate original continuation failure'))}
    for name,body in scripts.items():r.register_behavior(TEST+name,body);r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name in('buff','silence','give')else None))
    if mode:
        def eligible(c):return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==SHAKU
        def watch(c):
            if mode=='fail':return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),)),ChoiceOption('bounce','Return original attacker',(ReturnToHand(c.event.source_id),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible);r.register_card(CardDefinition(TEST+'watch','Original Shaku acquisition reaction',CardType.MINION,health=12,metadata=META,limited_triggers=(LimitedTriggerSpec('card_created',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

@lru_cache(maxsize=None)
def shared_registry(members,mode,pool):return registry(members,mode,pool)

class SimpleFollowupP46Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),deck=25,enemy_deck=24,members=MEMBERS,mode=None,pool=True,context=CONTEXT,hero='HERO_03',active=1):
        self.config=(members,mode,pool)
        if mode:board=(*board,TEST+'watch')
        own=(YETI,)*deck if type(deck)is int else deck;other=(YETI,)*enemy_deck
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=own,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',board=enemy,deck=other,mana=50,max_mana=50,mana_cap=50)),seed=4646,active_player=active,generation_context=context),shared_registry(*self.config))
    def first(self,g,cid,zone='hand',p=1):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        e=self.first(g,cid);g.apply(PlayCard(1,e.id,target,position=len(g.state.players[1].board)if e.kind==CardType.MINION else None));return e.id
    def attack(self,g,source=None,target=None,p=1):g.apply(Attack(p,self.first(g,SHAKU,'board',p).id if source is None else source,g.state.players[3-p].hero_id if target is None else target))
    def choose(self,g,key='ok'):g.apply(SelectChoice(1,g.state.pending_choice.id,(key,)))
    def created(self,g,source):return[g.state.entities[e.target_id]for e in g.events if e.kind=='card_created'and e.source_id==source]
    def actual(self,g):return resolve_candidates(g.registry,CONTEXT,POOL_ID,QUERY,source_card_id=SHAKU,exclude_source_by_rule=True,current_class=g.state.players[1].hero_class,player_id=1)
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','pool_basis','behavior_id','conditional_attack','stat_relation','character_attack_history'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_full_three_rows_four_faces_derived_metadata_current_shaku_stats_and_explicit_identity(self):
        d=load_batch();r=batch_registry();self.assertEqual((len(d['cards']),len(d['evidence_only']),len(d['official_observations']['observations'])),(2,1,4));norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']+d['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for row in d['cards']:
            raw=row['record'];c=r.card(raw['id']);meta=metadata_from_record(raw);self.assertEqual(c.metadata,replace(meta,deck_identity=LEGACY)if c.id==SHAKU else meta);self.assertEqual((c.cost,c.attack,c.health),(raw['cost'],raw['attack'],raw['health']));self.assertIsNone(c.spell_school);self.assertIsNone(c.on_play);self.assertIsNone(c.battlecry);self.assertIsNone(c.deathrattle);self.assertEqual(d['derived_metadata'][c.id],{'classes':[x.value for x in c.metadata.classes],'tribes':list(c.metadata.tribes),'rarity':c.metadata.rarity.value,'school':None})
            for o in(o for o in d['official_observations']['observations']if o['card_id']==c.id):
                f=o['face'];en=o['locale']=='en_US';self.assertEqual((f['id'],f['manaCost'],f['attack'],f['health']),(raw['dbf_id'],raw['cost'],raw['attack'],raw['health']));self.assertEqual(f['classId'],raw['tags']['CLASS']);self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']))
                if c.id==SHAKU:self.assertEqual(f['copyOfCardId'],[40905])
        raw=d['cards'][1]['record'];self.assertEqual((raw['tags']['858'],raw['tags']['DECK_RULE_COUNT_AS_COPY_OF_CARD_ID'],d['evidence_only'][0]['record']['dbf_id']),(40905,40905,40905));self.assertEqual((r.card(SHAKU).cost,r.card(SHAKU).attack,r.card(SHAKU).health),(3,2,4));self.assertEqual(r.card(SHAKU).keywords,(Keyword.STEALTH,));self.assertEqual(r.card(DEFENDER).keywords,(Keyword.TAUNT,));self.assertEqual(r.card(DEFENDER).stat_relations,(RELATION,));self.assertNotIn(LEGACY,r.cards);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])

    def test_only_two_new_defs_one_precise_pool_identity_exception_all_old_facts_default_maintained(self):
        with patch('hs_sim.cards.simple_followup_p46_cards.register_simple_followup_p46_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertTrue(all(asdict(c)==asdict(after.card(cid))for cid,c in before.cards.items()));self.assertEqual(set(before.pool_cards),set(after.pool_cards));changed=[cid for cid in before.pool_cards if before.pool_card(cid)!=after.pool_card(cid)];self.assertEqual(changed,[SHAKU]);self.assertEqual(after.pool_card(SHAKU),replace(before.pool_card(SHAKU),metadata=replace(before.pool_card(SHAKU).metadata,deck_identity=LEGACY)));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(dict(before.generation_families),dict(after.generation_families));self.assertEqual(before.card('TIME_021'),after.card('TIME_021'))
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT);self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in after.pools.values()))

    def test_defender_threshold_24_25_26_and_current_physical_deck_draw_add_7_2_7(self):
        for count,attack in((24,2),(25,7),(26,7)):
            with self.subTest(count=count):
                g=self.game(board=(DEFENDER,),deck=count,pool=False,context=None);source=self.first(g,DEFENDER,'board').id;self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(attack,7))
        g=self.game((TEST+'draw',TEST+'add'),board=(DEFENDER,),deck=(YETI,)*24+(MAGE,),pool=False,context=None);source=self.first(g,DEFENDER,'board').id;self.assertEqual(g.state.entities[source].attack,7);self.play(g,TEST+'draw');self.assertEqual((len(g.state.players[1].deck),g.state.entities[source].attack),(24,2));self.play(g,TEST+'add');self.assertEqual((len(g.state.players[1].deck),g.state.entities[source].attack),(25,7));self.assertEqual(g.state.entities[source].base_attack,2);self.portable(g)

    def test_defender_hand_and_grave_do_not_count_burn_still_removes_physical_deck_slot(self):
        g=self.game((TEST+'draw_burn',)+(YETI,)*9,board=(DEFENDER,),deck=25,pool=False,context=None);source=self.first(g,DEFENDER,'board').id;self.play(g,TEST+'draw_burn');self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(g.state.players[1].deck),24);self.assertEqual(g.state.entities[source].attack,2);self.assertTrue(any(e.kind=='card_burned'for e in g.events))

    def test_defender_control_deck_and_ordered_buff_silence_follow_common_relation(self):
        g=self.game((TEST+'give',TEST+'enemy_add'),board=(DEFENDER,),deck=25,enemy_deck=24,pool=False,context=None);source=self.first(g,DEFENDER,'board').id;self.play(g,TEST+'give',source);self.assertEqual((g.state.entities[source].controller,g.state.entities[source].attack),(2,2));self.play(g,TEST+'enemy_add');self.assertEqual(g.state.entities[source].attack,7)
        g=self.game((TEST+'buff',TEST+'draw',TEST+'add',TEST+'silence'),board=(DEFENDER,),deck=25,pool=False,context=None);source=self.first(g,DEFENDER,'board').id;self.play(g,TEST+'buff',source);self.assertEqual(g.state.entities[source].attack,10);self.play(g,TEST+'draw');self.assertEqual(g.state.entities[source].attack,5);self.play(g,TEST+'add');self.assertEqual(g.state.entities[source].attack,10);self.play(g,TEST+'silence',source);self.assertEqual(g.state.entities[source].attack,2);self.assertNotIn(Keyword.TAUNT,g.state.entities[source].keywords)

    def test_real_ordinary_play_or_summon_has_no_extra_body_or_battlecry_or_generation(self):
        g=self.game((DEFENDER,SHAKU),pool=False,context=None);a=self.play(g,DEFENDER);b=self.play(g,SHAKU);self.assertEqual(g.state.players[1].mana,43);self.assertEqual((g.state.entities[a].attack,g.state.entities[b].health),(7,4));self.assertFalse(self.created(g,b));self.assertFalse(g.state.battlecry_history)
        g=self.game((TEST+'natural',),pool=False,context=None);self.play(g,TEST+'natural');self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[DEFENDER,SHAKU]);self.assertFalse(g.state.battlecry_history);self.assertFalse(self.created(g,self.first(g,SHAKU,'board').id))

    def test_shaku_other_current_hero_class_query_excludes_neutral_and_any_shared_own_class(self):
        g=self.game(board=(SHAKU,));self.assertEqual({x.card_id for x in self.actual(g)},{SPELL,MINION,WEAPON,MAGE});self.assertEqual(QUERY.class_mode,'other');self.assertFalse(QUERY.include_neutral);self.assertFalse(QUERY.kinds)
        g=self.game(board=(SHAKU,),hero='HERO_08');self.assertEqual({x.card_id for x in self.actual(g)},{SHAKU,OWN,DUAL,SPELL,MINION,WEAPON}-{SHAKU});self.assertIn(OWN,{x.card_id for x in self.actual(g)});self.assertNotIn(MAGE,{x.card_id for x in self.actual(g)})

    def test_shaku_actual_source_attack_gets_one_playable_other_class_spell_minion_or_weapon(self):
        for member in(SPELL,MINION,WEAPON):
            with self.subTest(member=member):
                g=self.game(board=(SHAKU,),members=(member,));source=self.first(g,SHAKU,'board').id;rng=random.Random();rng.setstate(g._rng.getstate());sample_candidates(rng,self.actual(g),1,replacement=True);self.attack(g);new,=self.created(g,source);self.assertEqual((new.card_id,new.zone),(member,Zone.HAND));self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28);self.assertNotIn(Keyword.STEALTH,g.state.entities[source].keywords);row,=g.state.character_attack_history;self.assertEqual((row.declaration.source_id,row.source_card_id,row.terminal.status),(source,SHAKU,'completed'));self.assertEqual(g.state.entities[source].attacks_this_turn,1)

    def test_other_minion_hero_opponent_illegal_attacks_and_silenced_source_do_not_get(self):
        g=self.game(board=(SHAKU,YETI),pool=False,context=None);source=self.first(g,SHAKU,'board').id;self.attack(g,self.first(g,YETI,'board').id);self.assertFalse(self.created(g,source))
        g=self.game((TEST+'hero_attack',),board=(SHAKU,),pool=False,context=None);source=self.first(g,SHAKU,'board').id;self.play(g,TEST+'hero_attack');self.attack(g,g.state.players[1].hero_id);self.assertFalse(self.created(g,source))
        g=self.game(board=(SHAKU,),enemy=(YETI,),active=2,pool=False,context=None);source=self.first(g,SHAKU,'board').id;self.attack(g,self.first(g,YETI,'board',2).id,p=2);self.assertFalse(self.created(g,source))
        g=self.game(board=(SHAKU,),pool=False,context=None);source=self.first(g,SHAKU,'board').id;before=g.snapshot()
        with self.assertRaises(IllegalAction):self.attack(g,source,g.state.players[1].hero_id)
        self.assertEqual(g.snapshot(),before)
        g=self.game((TEST+'silence',),board=(SHAKU,),pool=False,context=None);source=self.first(g,SHAKU,'board').id;self.play(g,TEST+'silence',source);self.attack(g);self.assertFalse(self.created(g,source))

    def test_shaku_fullhand_burn_and_empty_other_class_pool_follow_original_attack(self):
        g=self.game((YETI,)*10,board=(SHAKU,),members=(SPELL,));source=self.first(g,SHAKU,'board').id;self.attack(g);new,=self.created(g,source);self.assertEqual(new.zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len([e for e in g.events if e.kind=='card_burned'and e.source_id==source]),1);self.assertEqual(g.state.character_attack_history[-1].terminal.status,'completed')
        g=self.game(board=(SHAKU,),members=(SHAKU,OWN,DUAL,YETI));source=self.first(g,SHAKU,'board').id;rng=g._rng.getstate();self.attack(g);self.assertFalse(self.created(g,source));self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28)

    def test_shaku_unknown_eligible_missing_context_and_pool_fail_before_rng_attack_rollback(self):
        for members,pool,context in(((SPELL,'CATA_483'),True,CONTEXT),(MEMBERS,True,None),(MEMBERS,False,CONTEXT)):
            with self.subTest(members=members,pool=pool):
                g=self.game(board=(SHAKU,),members=members,pool=pool,context=context);before=g.snapshot();calls=[];original=random.Random.randrange
                def spy(r,*a,**kw):calls.append(a);return original(r,*a,**kw)
                with patch.object(random.Random,'randrange',autospec=True,side_effect=spy):
                    with self.assertRaises(ResolutionError):self.attack(g)
                self.assertFalse(calls);self.assertEqual(g.snapshot(),before)

    def test_original_attack_acquisition_wait_fresh_restore_replay_bad_resume_and_completion_once(self):
        g=self.game(board=(SHAKU,),members=(SPELL,MINION),mode='wait');source=self.first(g,SHAKU,'board').id;self.attack(g);new,=self.created(g,source);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30);row,=g.state.character_attack_history;self.assertIsNone(row.terminal);self.assertIsNone(row.combat);other=self.portable(g);before=g.snapshot();rng=g._rng.getstate()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(self.created(g,source)),1);self.assertEqual(g.state.character_attack_history[-1].terminal.status,'completed');self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28);self.assertEqual(self.created(g,source)[0].id,new.id)

    def test_accepted_attack_get_remains_if_original_attacker_returns_before_combat_and_late_error_rolls_back(self):
        g=self.game(board=(SHAKU,),members=(SPELL,),mode='wait');source=self.first(g,SHAKU,'board').id;self.attack(g);rng=g._rng.getstate();self.choose(g,'bounce');self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.assertEqual(len(self.created(g,source)),1);self.assertEqual(g.state.character_attack_history[-1].terminal.status,'cancelled');self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30);self.assertEqual(g._rng.getstate(),rng)
        g=self.game(board=(SHAKU,),members=(SPELL,),mode='fail');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.attack(g)
        self.assertEqual(g.snapshot(),before)

if __name__=='__main__':unittest.main()
