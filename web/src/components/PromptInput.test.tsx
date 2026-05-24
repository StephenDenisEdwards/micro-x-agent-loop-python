import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PromptInput } from './PromptInput';

describe('PromptInput', () => {
  it('submits on Enter and clears the textarea', async () => {
    const onSubmit = vi.fn();
    render(<PromptInput onSubmit={onSubmit} />);
    const ta = screen.getByTestId('prompt-input') as HTMLTextAreaElement;
    await userEvent.type(ta, 'hello{Enter}');
    expect(onSubmit).toHaveBeenCalledWith('hello');
    expect(ta.value).toBe('');
  });

  it('does NOT submit on Shift+Enter — inserts newline', async () => {
    const onSubmit = vi.fn();
    render(<PromptInput onSubmit={onSubmit} />);
    const ta = screen.getByTestId('prompt-input') as HTMLTextAreaElement;
    await userEvent.type(ta, 'a{Shift>}{Enter}{/Shift}b');
    expect(onSubmit).not.toHaveBeenCalled();
    expect(ta.value).toBe('a\nb');
  });

  it('submits when the Send button is clicked', async () => {
    const onSubmit = vi.fn();
    render(<PromptInput onSubmit={onSubmit} />);
    await userEvent.type(screen.getByTestId('prompt-input'), 'message');
    await userEvent.click(screen.getByTestId('send-button'));
    expect(onSubmit).toHaveBeenCalledWith('message');
  });

  it('does not submit empty/whitespace-only input', async () => {
    const onSubmit = vi.fn();
    render(<PromptInput onSubmit={onSubmit} />);
    const ta = screen.getByTestId('prompt-input');
    await userEvent.type(ta, '   {Enter}');
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('disables the input and button when disabled prop is set', () => {
    render(<PromptInput onSubmit={() => {}} disabled />);
    expect(screen.getByTestId('prompt-input')).toBeDisabled();
    expect(screen.getByTestId('send-button')).toBeDisabled();
  });
});
