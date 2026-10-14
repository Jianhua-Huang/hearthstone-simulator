"""Complete and partial paid body policies, synthetic public extension example.

Policy IDs remain host-only; the real commands use seat-local body handles.
No official timing claim or automatic/generated body producer is made here.
"""
from dataclasses import replace
import json,sys
from hs_sim.engine import (BodyReference, BodyRootTargetBinding, BodyTargetBinding,
    BodyTargetProfile, CardDefinition, CardType, Game, GrantBattlecry, GrantCombo,
    Keyword, PlayerSetup, Registry, Scenario, TargetMode, TargetSpec, Zone)
from hs_sim.engine.body_grants import RemoveGrantedBody
from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, GainArmor, RequestChoice,
    RandomDamage, Summon)
from hs_sim.engine.zones import CardReference, CopyCard

FRIEND=TargetSpec(TargetMode.IF_AVAILABLE,(Zone.BOARD,),(CardType.MINION,),'friendly')
ENEMY=replace(FRIEND,mode=TargetMode.REQUIRED,relation='enemy')


def profiles(reverse=False):
    return ('paid_a','paid_z') if reverse else ('paid_z','paid_a')


def registry(mode='normal',reverse=False):
    complete,partial=profiles(reverse)
    r=Registry('multiple-body-policies-'+mode+'-'+str(reverse))
    for profile in (complete,partial):
        r.register_body_target_profile(BodyTargetProfile(profile,'paid_hand','manual','pre_payment'))
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=100))
    for name in ('friend','enemy','hidden'):
        r.register_card(CardDefinition(name,name,CardType.MINION,attack=1,health=20))
    def body(c):
        effects=[GainArmor(c.player_id,1)]
        if c.target_id is not None:effects.append(Buff(c.target_id,attack=1,source_id=c.source_id))
        if mode=='wait' and c.combo is not None:
            return [RequestChoice(c.player_id,(ChoiceOption('go','Continue',tuple(effects)),),c.source_id)]
        if mode=='fail' and c.combo is not None:
            return [RandomDamage((c.state.players[2].hero_id,),1,source_id=c.source_id),Summon(c.player_id,'unsupported.body')]
        return effects
    r.register_behavior('body',body)
    r.register_behavior('root',lambda c:[Damage(c.target_id,2,c.source_id)])
    # Executable custom rules deliberately remain unsupported by this consumer.
    r.register_target_rule('unsafe',lambda c:(_ for _ in ()).throw(AssertionError('custom predicate executed')))
    r.register_card(CardDefinition('unit','Unit',CardType.MINION,cost=2,attack=1,health=20,
        battlecry='body',on_play='root',targeting=FRIEND))
    r.register_card(CardDefinition('empty','Empty carrier',CardType.MINION,cost=2,attack=1,health=20))
    r.register_card(CardDefinition('enemy_body','Enemy body',CardType.MINION,health=5,battlecry='body',targeting=ENEMY))
    r.register_card(CardDefinition('no_combo','No target combo',CardType.MINION,health=5,combo='body',keywords=(Keyword.COMBO,)))
    r.register_card(CardDefinition('alternate','Alternate body',CardType.MINION,health=5,battlecry='body',targeting=FRIEND))
    def source(c,name='unit'):
        return next(e for e in c.state.entities.values() if e.card_id==name and e.controller==c.player_id and e.zone==Zone.HAND)
    r.register_behavior('setup',lambda c:[GrantBattlecry(BodyReference.capture(source(c)),'enemy_body',c.source_id),
        GrantCombo(BodyReference.capture(source(c)),'no_combo',c.source_id)])
    r.register_behavior('copy',lambda c:[CopyCard(CardReference.capture(source(c)),c.player_id,source_id=c.source_id)])
    for name,declaration in (('grant_a','enemy_body'),('grant_b','alternate')):
        r.register_behavior(name,lambda c,declaration=declaration:[GrantBattlecry(BodyReference.capture(source(c,'empty')),declaration,c.source_id)])
    def remove(c):
        e=source(c,'empty');ability=next(a for a in e.abilities if a.kind=='battlecry' and a.origin=='granted')
        return [RemoveGrantedBody(BodyReference.capture(e),ability.id,'battlecry',c.source_id)]
    r.register_behavior('remove',remove)
    for name in ('setup','copy','grant_a','grant_b','remove'):
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name))
    options={}
    if mode=='scope_kind':options['carrier_kinds']=(CardType.WEAPON,)
    if mode=='scope_card':options['carrier_card_ids']=('friend',)
    if mode!='missing':r.register_body_target_binding(BodyTargetBinding('unit','battlecry',complete,('printed',),**options))
    r.register_body_target_binding(BodyTargetBinding('unit','battlecry',partial,('granted',)))
    r.register_body_target_binding(BodyTargetBinding('enemy_body','battlecry',partial if mode=='split' else complete,('granted',)))
    r.register_body_target_binding(BodyTargetBinding('no_combo','combo',complete,('granted',)))
    r.register_body_target_binding(BodyTargetBinding('alternate','battlecry',partial,('granted',)))
    r.register_body_root_target_binding(BodyRootTargetBinding('unit',complete,'explicit_root',ENEMY,
        target_rule='unsafe' if mode=='custom_complete' else 'any_entity'))
    r.register_body_root_target_binding(BodyRootTargetBinding('unit',partial,'explicit_root',ENEMY,target_rule='unsafe'))
    for profile in (complete,partial):r.register_body_root_target_binding(BodyRootTargetBinding('empty',profile,'body_only'))
    return r


def scenario(*,switch=False,enemy_card='hidden',copy=False):
    hand=('grant_a','remove','grant_b','empty') if switch else ('setup','unit',*(('copy',) if copy else ()))
    return Scenario((PlayerSetup('hero',hand=hand,board=('friend',),mana=10,max_mana=10),
        PlayerSetup('hero',hand=(enemy_card,),board=('enemy',),mana=10,max_mana=10)),seed=41)


def ref(game,name,index=0):
    hand=game.for_player(1).observe()['observation']['players'][0]['hand']
    return [c['ref'] for c in hand if c.get('card_id')==name][index]


def spell_command(game,name):
    return {'revision':game.for_player(1).observe()['revision'],'action':{'type':'play_card','card':ref(game,name)}}


def paid_command(game,name='unit',index=0,position=0):
    result=game.for_player(1).independent_targets(ref(game,name,index),position=position)
    assert result['error'] is None and len(result['choices'])==1,result
    choice=result['choices'][0]
    return {'revision':result['revision'],'action':{'type':'play_card','card':choice['card'],'position':position,
        'target':choice['root_targets'][0],'body_targets':[{'body':b['body'],'target':b['targets'][0]} for b in choice['bodies']]}}


def main():
    mode=sys.argv[1] if len(sys.argv)>1 else 'normal'
    game=Game.from_scenario(scenario(switch=mode=='switch'),registry(mode))
    initial=game.snapshot();commands=[];positions=[]
    def submit(command):
        response=game.for_player(1).submit(command);assert response['accepted'],response
        commands.append(command)
        positions.append({'after_commands':len(commands),'snapshot':game.snapshot(),
            'observations':[game.for_player(p).observe() for p in (1,2)],'waiting':game.state.pending_choice is not None})
    if mode=='switch':
        for name in ('grant_a','remove','grant_b'):submit(spell_command(game,name))
        submit(paid_command(game,'empty'))
    else:
        submit(spell_command(game,'setup'));submit(paid_command(game))
        while game.state.pending_choice is not None:
            legal=game.for_player(1).legal_actions();assert legal['error'] is None
            submit({'revision':legal['revision'],'action':legal['actions'][0]})
    print(json.dumps({'mode':mode,'initial':initial,'commands':commands,'positions':positions,'final':game.snapshot()},ensure_ascii=False))


if __name__=='__main__':main()
