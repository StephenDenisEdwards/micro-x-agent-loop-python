import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AskUserModal } from './AskUserModal';

describe('AskUserModal', () => {
  it('renders the question text', () => {
    render(
      <AskUserModal
        question={{ id: 'q1', text: 'Continue?', options: null }}
        onAnswer={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByTestId('ask-user-question')).toHaveTextContent('Continue?');
  });

  it('renders option buttons when options are provided and answers with the value', async () => {
    const onAnswer = vi.fn();
    render(
      <AskUserModal
        question={{
          id: 'q1',
          text: 'Pick',
          options: [
            { value: 'yes', label: 'Yes' },
            { value: 'no', label: 'No' },
          ],
        }}
        onAnswer={onAnswer}
        onCancel={() => {}}
      />,
    );
    const buttons = screen.getAllByTestId('ask-user-option');
    expect(buttons).toHaveLength(2);
    await userEvent.click(buttons[0]!);
    expect(onAnswer).toHaveBeenCalledWith('yes');
  });

  it('answers via Enter from the text input', async () => {
    const onAnswer = vi.fn();
    render(
      <AskUserModal
        question={{ id: 'q1', text: 'why?', options: null }}
        onAnswer={onAnswer}
        onCancel={() => {}}
      />,
    );
    await userEvent.type(screen.getByTestId('ask-user-input'), 'because{Enter}');
    expect(onAnswer).toHaveBeenCalledWith('because');
  });

  it('cancels on Escape', async () => {
    const onCancel = vi.fn();
    render(
      <AskUserModal
        question={{ id: 'q1', text: 'why?', options: null }}
        onAnswer={() => {}}
        onCancel={onCancel}
      />,
    );
    await userEvent.click(screen.getByTestId('ask-user-input'));
    await userEvent.keyboard('{Escape}');
    expect(onCancel).toHaveBeenCalled();
  });

  it('disables Send while the input is empty', () => {
    render(
      <AskUserModal
        question={{ id: 'q1', text: 'why?', options: null }}
        onAnswer={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByTestId('ask-user-submit')).toBeDisabled();
  });
});
