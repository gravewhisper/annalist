const saved = v => Object.values(v.disk).filter(d => !('none' in d)).length;
const pend = v => ('none' in v.pending) ? '' : `, ch ${v.pending.n} check ${v.pending.check}`;
export const title = 'Annalist read stage';
export const state = v => {
  if (v.pc === 'down') return `Not running, ${saved(v)} saved`;
  if (v.pc === 'exit') return `Run ended, ${saved(v)} saved`;
  if (v.pc === 'errOrder') return 'Refused: "read in order"';
  if (v.pc === 'errLater') return 'Refused: "later chapters were read"';
  if (v.pc === 'stop') return `Stopping after a failure${pend(v)}`;
  return `Reading, ${saved(v)} saved${pend(v)}`;
};
export const group = v => v.pc.startsWith('err') ? 'broken' : (v.pc === 'down' || v.pc === 'exit') ? 'idle' : 'reading';
export const colors = {broken: 'orange', idle: 'tan', reading: 'blue'};
const words = {
  Run: 'you run the build', LoopEnd: 'reaches --to', SkipSaved: 'skips a saved chapter', RefuseOrder: 'read-in-order check refuses',
  RefuseLater: 'later-chapters check refuses', ExtractOk: 'a chapter extract returns', ExtractFails: 'an extract call fails',
  NoPendingSubmit: 'its check starts', SavePendingThenSubmit: 'previous chapter saved, its check starts',
  PendingCheckFailed: 'the previous check had failed', StopSaves: 'saves the earlier chapter and exits', StopExits: 'exits',
  FinalSave: 'saves the last chapter and exits', FinalExits: 'exits', CheckOk: 'a check passes', CheckFails: 'a check fails',
  Killed: 'the process is killed',
};
export const step = action => words[action] ?? action;
